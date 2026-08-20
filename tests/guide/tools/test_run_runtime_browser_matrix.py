from __future__ import annotations

import errno
import json
import os
from pathlib import Path
import socket
import stat
import subprocess
import sys
import time

import pytest

import tools.guide_gates.run_runtime_browser_matrix as browser_matrix
from tools.guide_gates.run_runtime_browser_matrix import (
    BROWSER_COMMANDS,
    SERVER_COMMAND,
    run_browser_matrix,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
REQUIRED_BROWSER_MODULES = (
    "numpy",
    "torch",
    "open_clip",
    "rapidocr_onnxruntime",
    "playwright",
)


def _requirement_lines(requirements: str) -> set[str]:
    return {
        line
        for raw_line in requirements.splitlines()
        if (line := raw_line.strip()) and not line.startswith("#")
    }


def _shadow_browser_environment(
    tmp_path: Path,
    *,
    failing_component: str | None,
    secret: str,
) -> tuple[dict[str, str], Path, Path]:
    shadow_root = tmp_path / "shadow-modules"
    shadow_root.mkdir()
    trace_path = tmp_path / "import-trace.txt"
    server_marker = tmp_path / "uvicorn-started"

    common = (
        "import os\n"
        "from pathlib import Path\n"
        "import sys\n"
        "with Path(os.environ['BROWSER_MATRIX_IMPORT_TRACE']).open(\n"
        "    'a', encoding='utf-8'\n"
        ") as trace:\n"
        "    trace.write(f'{__name__.split(\".\")[0]}:{sys.executable}\\n')\n"
    )
    failure = (
        "secret = os.environ['BROWSER_MATRIX_TEST_SECRET']\n"
        "print(secret)\n"
        "print(secret, file=sys.stderr)\n"
        "raise ImportError(secret)\n"
    )
    for module_name in REQUIRED_BROWSER_MODULES[:-1]:
        (shadow_root / f"{module_name}.py").write_text(
            common + (failure if failing_component == module_name else ""),
            encoding="utf-8",
        )

    playwright_package = shadow_root / "playwright"
    playwright_package.mkdir()
    (playwright_package / "__init__.py").write_text(
        common + (failure if failing_component == "playwright" else ""),
        encoding="utf-8",
    )
    (playwright_package / "sync_api.py").write_text(
        (
            "import os\n"
            "\n"
            "class _Chromium:\n"
            "    executable_path = os.environ[\n"
            "        'PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH'\n"
            "    ]\n"
            "\n"
            "class _Playwright:\n"
            "    chromium = _Chromium()\n"
            "\n"
            "class _Manager:\n"
            "    def __enter__(self):\n"
            "        return _Playwright()\n"
            "\n"
            "    def __exit__(self, *args):\n"
            "        return False\n"
            "\n"
            "def sync_playwright():\n"
            "    return _Manager()\n"
        ),
        encoding="utf-8",
    )
    (shadow_root / "uvicorn.py").write_text(
        (
            "from pathlib import Path\n"
            f"Path({str(server_marker)!r}).write_text("
            "'started', encoding='utf-8')\n"
        ),
        encoding="utf-8",
    )

    browser_runtime = tmp_path / "chromium"
    if failing_component != "browser_runtime":
        browser_runtime.write_text("#!/bin/sh\n", encoding="utf-8")
        browser_runtime.chmod(0o700)

    environment = dict(os.environ)
    environment.update(
        {
            "BROWSER_MATRIX_IMPORT_TRACE": str(trace_path),
            "BROWSER_MATRIX_TEST_SECRET": secret,
            "PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH": str(browser_runtime),
            "PYTHONPATH": str(shadow_root),
        }
    )
    return environment, server_marker, trace_path


def _unused_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _fake_http_server_command(
    port: int,
    *,
    ignore_term: bool = False,
) -> tuple[str, ...]:
    setup = (
        "import signal;"
        "signal.signal(signal.SIGTERM,signal.SIG_IGN);"
        if ignore_term
        else ""
    )
    code = (
        "from http.server import BaseHTTPRequestHandler,HTTPServer;"
        + setup
        + "H=type('H',(BaseHTTPRequestHandler,),{"
        "'do_GET':lambda s:"
        "(s.send_response(200),s.end_headers(),s.wfile.write(b'ok')),"
        "'log_message':lambda *a:None});"
        f"HTTPServer(('127.0.0.1',{port}),H).serve_forever()"
    )
    return (sys.executable, "-c", code)


def _process_is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def _wait_until_process_exits(marker: str) -> bool:
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        completed = subprocess.run(
            ["ps", "-axo", "command="],
            check=True,
            capture_output=True,
            text=True,
        )
        if marker not in completed.stdout:
            return True
        time.sleep(0.05)
    return False


def test_browser_matrix_requirements_lock_compatible_complete_runtime() -> None:
    requirements = (
        REPOSITORY_ROOT / "requirements-guide-browser-matrix.txt"
    ).read_text(encoding="utf-8")
    requirement_lines = _requirement_lines(requirements)

    assert "-r requirements-guide-runtime-test.txt" in requirement_lines
    assert all(
        "requirements-guide-image.txt" not in line
        for line in requirement_lines
    )
    assert {
        "open_clip_torch==3.3.0",
        "playwright==1.60.0",
        "rapidocr-onnxruntime==1.3.0",
        "torchvision==0.27.0",
    } <= requirement_lines
    assert not any(
        line.lower().startswith(("httpx", "pillow"))
        for line in requirement_lines
    )


@pytest.mark.parametrize(
    "missing_component",
    (*REQUIRED_BROWSER_MODULES, "browser_runtime"),
)
def test_default_matrix_preflight_fails_before_server_for_missing_environment(
    tmp_path: Path,
    missing_component: str,
) -> None:
    output_dir = tmp_path / "matrix-output"
    secret = f"secret-for-{missing_component}-must-not-leak"
    environment, server_marker, trace_path = _shadow_browser_environment(
        tmp_path,
        failing_component=missing_component,
        secret=secret,
    )

    result = run_browser_matrix(
        output_dir=output_dir,
        env=environment,
        timeout_seconds=0.2,
        heartbeat_seconds=0.05,
        ready_timeout_seconds=0.2,
        termination_grace_seconds=0.1,
    )

    assert not server_marker.exists()
    assert result.returncode == 2
    assert result.server_pid is None
    assert result.server_ready is False
    assert result.probes == ()
    assert result.environment_failure is not None
    assert result.environment_failure.code == (
        "browser_environment_unavailable"
    )
    assert (
        missing_component,
        "unavailable",
    ) in {
        (check.component, check.code)
        for check in result.environment_failure.checks
    }

    observed_imports = {
        module_name: executable
        for line in trace_path.read_text(encoding="utf-8").splitlines()
        for module_name, executable in (line.split(":", 1),)
    }
    assert observed_imports == {
        module_name: sys.executable
        for module_name in REQUIRED_BROWSER_MODULES
    }

    summary_path = output_dir / browser_matrix.SUMMARY_FILENAME
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["status"] == "failed"
    assert summary["returncode"] == 2
    assert summary["server"]["pid"] is None
    assert summary["probes"] == []
    assert summary["environment_failure"]["code"] == (
        "browser_environment_unavailable"
    )
    output_bytes = b"".join(
        path.read_bytes() for path in sorted(output_dir.iterdir())
    )
    assert secret.encode() not in output_bytes


def test_default_commands_target_guide_runtime_and_existing_probes() -> None:
    assert SERVER_COMMAND == (
        sys.executable,
        "-m",
        "uvicorn",
        "app.guide_runtime.app:app",
        "--host",
        "127.0.0.1",
        "--port",
        "8765",
    )
    assert BROWSER_COMMANDS == (
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


def test_cli_supports_the_planned_repo_relative_script_path() -> None:
    repository_root = Path(__file__).resolve().parents[3]

    completed = subprocess.run(
        [
            sys.executable,
            "tools/guide_gates/run_runtime_browser_matrix.py",
            "--help",
        ],
        cwd=repository_root,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert "--timeout-seconds" in completed.stdout
    assert "--heartbeat-seconds" in completed.stdout


def test_browser_matrix_runs_probes_in_order_and_stops_server_group(
    tmp_path: Path,
) -> None:
    port = _unused_port()
    output_dir = tmp_path / "matrix-output"
    order_path = tmp_path / "order.txt"
    append = (
        "from pathlib import Path;"
        f"p=Path({str(order_path)!r});"
        "p.write_text((p.read_text() if p.exists() else '')+"
    )
    browser_commands = (
        (sys.executable, "-c", append + "'normal\\n')"),
        (sys.executable, "-c", append + "'adversarial\\n')"),
    )

    result = run_browser_matrix(
        server_command=_fake_http_server_command(port),
        browser_commands=browser_commands,
        ready_url=f"http://127.0.0.1:{port}/health",
        timeout_seconds=2,
        heartbeat_seconds=0.05,
        ready_timeout_seconds=2,
        termination_grace_seconds=0.2,
        output_dir=output_dir,
    )

    assert result.returncode == 0
    assert result.server_ready is True
    assert result.server_term_sent is True
    assert result.server_kill_sent is False
    assert not _process_is_alive(result.server_pid)
    assert [probe.name for probe in result.probes] == [
        "normal",
        "adversarial",
    ]
    assert order_path.read_text(encoding="utf-8") == (
        "normal\nadversarial\n"
    )
    assert stat.S_IMODE(output_dir.stat().st_mode) == 0o700
    for filename in (
        "server.log",
        "normal.log",
        "adversarial.log",
        "runtime_browser_matrix_summary.json",
    ):
        path = output_dir / filename
        assert path.is_file()
        assert not path.is_symlink()
        assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_failed_probe_skips_remaining_probe_and_stops_server(
    tmp_path: Path,
) -> None:
    port = _unused_port()
    output_dir = tmp_path / "matrix-output"
    forbidden_path = tmp_path / "must-not-run"

    result = run_browser_matrix(
        server_command=_fake_http_server_command(port),
        browser_commands=(
            (sys.executable, "-c", "raise SystemExit(7)"),
            (
                sys.executable,
                "-c",
                f"open({str(forbidden_path)!r},'w').close()",
            ),
        ),
        ready_url=f"http://127.0.0.1:{port}/health",
        timeout_seconds=2,
        heartbeat_seconds=0.05,
        ready_timeout_seconds=2,
        termination_grace_seconds=0.2,
        output_dir=output_dir,
    )

    assert result.returncode == 7
    assert [probe.name for probe in result.probes] == ["normal"]
    assert not forbidden_path.exists()
    assert (output_dir / "adversarial.log").read_bytes() == b""
    assert result.server_term_sent is True
    assert not _process_is_alive(result.server_pid)


def test_probe_timeout_cleans_up_probe_group_and_server(
    tmp_path: Path,
) -> None:
    port = _unused_port()
    output_dir = tmp_path / "matrix-output"
    marker = f"runtime-browser-timeout-{os.getpid()}-{port}"

    result = run_browser_matrix(
        server_command=_fake_http_server_command(port),
        browser_commands=(
            (
                sys.executable,
                "-c",
                "import time;time.sleep(60)",
                marker,
            ),
        ),
        ready_url=f"http://127.0.0.1:{port}/health",
        timeout_seconds=0.2,
        heartbeat_seconds=0.05,
        ready_timeout_seconds=2,
        termination_grace_seconds=0.1,
        output_dir=output_dir,
    )

    assert result.returncode == 124
    assert result.probes[0].timed_out is True
    assert result.probes[0].term_sent is True
    assert _wait_until_process_exits(marker)
    assert not _process_is_alive(result.server_pid)


def test_private_typed_summary_omits_commands_and_environment_values(
    tmp_path: Path,
) -> None:
    port = _unused_port()
    output_dir = tmp_path / "matrix-output"
    secret = "browser-matrix-secret-must-not-leak"
    environment = dict(os.environ)
    environment["BROWSER_MATRIX_TEST_SECRET"] = secret

    result = run_browser_matrix(
        server_command=_fake_http_server_command(port, ignore_term=True),
        browser_commands=((sys.executable, "-c", "pass", secret),),
        ready_url=f"http://127.0.0.1:{port}/health",
        timeout_seconds=2,
        heartbeat_seconds=0.05,
        ready_timeout_seconds=2,
        termination_grace_seconds=0.1,
        output_dir=output_dir,
        env=environment,
    )

    summary_path = output_dir / "runtime_browser_matrix_summary.json"
    summary_text = summary_path.read_text(encoding="utf-8")
    summary = json.loads(summary_text)
    assert result.returncode == 0
    assert result.server_term_sent is True
    assert result.server_kill_sent is True
    assert stat.S_IMODE(summary_path.stat().st_mode) == 0o600
    assert summary["schema_version"] == 1
    assert summary["status"] == "passed"
    assert summary["server"]["ready"] is True
    assert summary["server"]["term_sent"] is True
    assert summary["server"]["kill_sent"] is True
    assert summary["probes"][0]["name"] == "normal"
    assert "command" not in summary_text.lower()
    assert secret not in summary_text
    assert "BROWSER_MATRIX_TEST_SECRET" not in summary_text
    assert not _process_is_alive(result.server_pid)


@pytest.mark.parametrize("path_kind", ["directory", "symlink"])
def test_browser_matrix_rejects_preexisting_output_path_before_launch(
    tmp_path: Path,
    path_kind: str,
) -> None:
    output_dir = tmp_path / "matrix-output"
    target_dir = tmp_path / "attacker-controlled"
    target_dir.mkdir()
    if path_kind == "directory":
        output_dir.mkdir()
    else:
        output_dir.symlink_to(target_dir, target_is_directory=True)
    launch_marker = tmp_path / "server-was-launched"
    server_command = (
        sys.executable,
        "-c",
        (
            "from pathlib import Path;"
            f"Path({str(launch_marker)!r}).write_text('launched')"
        ),
    )

    with pytest.raises(FileExistsError):
        run_browser_matrix(
            server_command=server_command,
            browser_commands=(),
            ready_url="http://127.0.0.1:1/health",
            timeout_seconds=0.1,
            heartbeat_seconds=0.05,
            ready_timeout_seconds=0.1,
            termination_grace_seconds=0.1,
            output_dir=output_dir,
        )

    assert not launch_marker.exists()
    assert list(target_dir.iterdir()) == []


def test_browser_matrix_precreates_all_outputs_before_server_launch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_dir = tmp_path / "matrix-output"
    launch_failure = OSError("simulated server launch failure")
    observed_paths: tuple[bool, ...] = ()

    def fail_launch(*args, **kwargs):
        nonlocal observed_paths
        observed_paths = tuple(
            (output_dir / filename).is_file()
            for filename in (
                "server.log",
                "normal.log",
                "adversarial.log",
                "runtime_browser_matrix_summary.json",
            )
        )
        raise launch_failure

    monkeypatch.setattr(browser_matrix.subprocess, "Popen", fail_launch)

    with pytest.raises(OSError) as caught:
        run_browser_matrix(
            server_command=(sys.executable, "-c", "pass"),
            browser_commands=(
                (sys.executable, "-c", "pass"),
                (sys.executable, "-c", "pass"),
            ),
            ready_url="http://127.0.0.1:1/health",
            timeout_seconds=0.1,
            heartbeat_seconds=0.05,
            ready_timeout_seconds=0.1,
            termination_grace_seconds=0.1,
            output_dir=output_dir,
        )

    assert caught.value is launch_failure
    assert observed_paths == (True, True, True, True)
    summary = json.loads(
        (output_dir / "runtime_browser_matrix_summary.json").read_text(
            encoding="utf-8"
        )
    )
    assert summary["status"] == "failed"
    assert summary["failure_type"] == "OSError"


def test_probe_log_symlink_swap_cannot_redirect_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    port = _unused_port()
    output_dir = tmp_path / "matrix-output"
    target = tmp_path / "attacker-target"
    original = b"attacker target must remain unchanged\n"
    target.write_bytes(original)
    real_run_bounded = browser_matrix.run_bounded

    def swap_path_before_probe_write(command, **kwargs):
        probe_log = output_dir / "normal.log"
        assert probe_log.is_file()
        probe_log.unlink()
        probe_log.symlink_to(target)
        return real_run_bounded(command, **kwargs)

    monkeypatch.setattr(
        browser_matrix,
        "run_bounded",
        swap_path_before_probe_write,
    )

    failure: BaseException | None = None
    try:
        run_browser_matrix(
            server_command=_fake_http_server_command(port),
            browser_commands=(
                (sys.executable, "-c", "print('probe output')"),
            ),
            ready_url=f"http://127.0.0.1:{port}/health",
            timeout_seconds=2,
            heartbeat_seconds=0.05,
            ready_timeout_seconds=2,
            termination_grace_seconds=0.2,
            output_dir=output_dir,
        )
    except BaseException as exc:
        failure = exc

    assert target.read_bytes() == original
    assert failure is not None
    assert type(failure).__name__ == "OutputBindingError"


@pytest.mark.parametrize(
    "raise_after_swap",
    [False, True],
    ids=["completion", "exception"],
)
def test_output_directory_replacement_is_a_typed_binding_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    raise_after_swap: bool,
) -> None:
    port = _unused_port()
    output_dir = tmp_path / "matrix-output"
    detached_dir = tmp_path / "detached-output"
    injected_failure = OSError("simulated probe adapter failure")
    real_run_bounded = browser_matrix.run_bounded

    def replace_directory_after_probe(command, **kwargs):
        result = real_run_bounded(command, **kwargs)
        output_dir.rename(detached_dir)
        output_dir.mkdir(mode=0o700)
        if raise_after_swap:
            raise injected_failure
        return result

    monkeypatch.setattr(
        browser_matrix,
        "run_bounded",
        replace_directory_after_probe,
    )

    with pytest.raises(browser_matrix.OutputBindingError):
        run_browser_matrix(
            server_command=_fake_http_server_command(port),
            browser_commands=((sys.executable, "-c", "pass"),),
            ready_url=f"http://127.0.0.1:{port}/health",
            timeout_seconds=2,
            heartbeat_seconds=0.05,
            ready_timeout_seconds=2,
            termination_grace_seconds=0.2,
            output_dir=output_dir,
        )

    assert output_dir.is_dir()
    assert list(output_dir.iterdir()) == []
    assert detached_dir.is_dir()


def test_server_log_fdopen_failure_closes_duplicated_descriptor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_dir = tmp_path / "matrix-output"
    fdopen_failure = OSError("simulated fdopen failure")
    real_dup = os.dup
    duplicated_descriptor: int | None = None

    def track_dup(descriptor: int) -> int:
        nonlocal duplicated_descriptor
        duplicated_descriptor = real_dup(descriptor)
        return duplicated_descriptor

    def fail_fdopen(*args, **kwargs):
        raise fdopen_failure

    monkeypatch.setattr(browser_matrix.os, "dup", track_dup)
    monkeypatch.setattr(browser_matrix.os, "fdopen", fail_fdopen)

    with pytest.raises(OSError) as caught:
        run_browser_matrix(
            server_command=(sys.executable, "-c", "pass"),
            browser_commands=(),
            ready_url="http://127.0.0.1:1/health",
            timeout_seconds=0.1,
            heartbeat_seconds=0.05,
            ready_timeout_seconds=0.1,
            termination_grace_seconds=0.1,
            output_dir=output_dir,
        )

    assert caught.value is fdopen_failure
    assert duplicated_descriptor is not None
    try:
        os.fstat(duplicated_descriptor)
    except OSError as exc:
        assert exc.errno == errno.EBADF
    else:
        os.close(duplicated_descriptor)
        pytest.fail("duplicated server log descriptor was leaked")
