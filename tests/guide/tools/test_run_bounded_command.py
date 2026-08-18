from __future__ import annotations

import importlib
import json
import os
from pathlib import Path
import signal
import stat
import subprocess
import sys
import time
import uuid

import pytest


def _runner_module():
    return importlib.import_module(
        "tools.guide_gates.run_bounded_command"
    )


_OPEN_OUTPUT_FDS: set[int] = set()


def _output_fd(
    path: Path,
    *,
    flags: int = os.O_WRONLY | os.O_CREAT | os.O_EXCL,
) -> int:
    descriptor = os.open(path, flags | os.O_CLOEXEC, 0o600)
    _OPEN_OUTPUT_FDS.add(descriptor)
    return descriptor


@pytest.fixture(autouse=True)
def _close_output_fds() -> None:
    yield
    while _OPEN_OUTPUT_FDS:
        descriptor = _OPEN_OUTPUT_FDS.pop()
        try:
            os.close(descriptor)
        except OSError:
            pass


def _process_contains(marker: str) -> bool:
    completed = subprocess.run(
        ["ps", "-axo", "command="],
        check=True,
        capture_output=True,
        text=True,
    )
    return marker in completed.stdout


def _wait_until_process_exits(marker: str) -> bool:
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        if not _process_contains(marker):
            return True
        time.sleep(0.05)
    return not _process_contains(marker)


def test_runner_emits_heartbeat_and_writes_private_evidence(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _runner_module()
    output_path = tmp_path / "run.log"
    output_fd = _output_fd(output_path)
    secret = "summary-must-not-contain-this-value"
    environment = dict(os.environ)
    environment["RUNNER_TEST_SECRET"] = secret
    monkeypatch.setattr(
        runner.os,
        "open",
        lambda *args, **kwargs: pytest.fail(
            "run_bounded must not reopen an output path"
        ),
    )

    result = runner.run_bounded(
        [
            sys.executable,
            "-c",
            (
                "import os,time;"
                "print('started',flush=True);"
                "assert os.environ['RUNNER_TEST_SECRET'];"
                "time.sleep(0.15);"
                "print('done',flush=True)"
            ),
        ],
        timeout_seconds=2,
        heartbeat_seconds=0.05,
        output_fd=output_fd,
        env=environment,
    )

    assert result.returncode == 0
    assert result.timed_out is False
    assert result.term_sent is False
    assert result.kill_sent is False
    assert result.output_lines == 2
    assert output_path.read_text(encoding="utf-8") == "started\ndone\n"
    assert stat.S_IMODE(output_path.stat().st_mode) == 0o600
    assert os.fstat(output_fd).st_ino == output_path.stat().st_ino

    captured = capsys.readouterr()
    assert captured.out == ""
    heartbeat_lines = captured.err.splitlines()
    assert heartbeat_lines
    assert all(
        line.startswith("heartbeat elapsed=")
        and " output_lines=" in line
        for line in heartbeat_lines
    )
    assert "started" not in captured.err
    assert "done" not in captured.err


def test_runner_returns_nonzero_child_code(tmp_path: Path) -> None:
    runner = _runner_module()

    result = runner.run_bounded(
        [sys.executable, "-c", "raise SystemExit(7)"],
        timeout_seconds=2,
        heartbeat_seconds=0.05,
        output_fd=_output_fd(tmp_path / "nonzero.log"),
    )

    assert result.returncode == 7
    assert result.timed_out is False


def test_runner_preserves_caller_fd_when_launch_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _runner_module()
    marker = f"bounded-launch-failure-{uuid.uuid4().hex}"
    output_path = tmp_path / "launch-failure.log"
    output_fd = _output_fd(output_path)
    launch_failure = OSError("simulated launch failure")

    with monkeypatch.context() as patcher:
        def fail_launch(*args, **kwargs):
            raise launch_failure

        patcher.setattr(runner.subprocess, "Popen", fail_launch)

        with pytest.raises(OSError) as caught:
            runner.run_bounded(
                [sys.executable, "-c", "pass", marker],
                timeout_seconds=2,
                heartbeat_seconds=0.05,
                output_fd=output_fd,
            )

    assert caught.value is launch_failure
    assert os.fstat(output_fd).st_ino == output_path.stat().st_ino
    assert stat.S_IMODE(output_path.stat().st_mode) == 0o600
    assert not _process_contains(marker)


def test_cli_writes_private_failure_summary_when_launch_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _runner_module()
    launch_failure = OSError("simulated launch failure")
    output_path = tmp_path / "launch-failure.log"
    summary_path = tmp_path / "launch-failure.json"

    def fail_launch(*args, **kwargs):
        raise launch_failure

    monkeypatch.setattr(runner.subprocess, "Popen", fail_launch)

    returncode = runner.main(
        [
            "--timeout-seconds",
            "2",
            "--heartbeat-seconds",
            "0.05",
            "--output",
            str(output_path),
            "--summary",
            str(summary_path),
            "--",
            sys.executable,
            "-c",
            "pass",
        ]
    )

    assert returncode == 1
    assert stat.S_IMODE(output_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(summary_path.stat().st_mode) == 0o600
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["status"] == "failed"
    assert summary["failure"] == {
        "message": "simulated launch failure",
        "type": "OSError",
    }


def test_runner_cleans_up_and_preserves_fd_on_reader_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _runner_module()
    marker = f"bounded-reader-failure-{uuid.uuid4().hex}"
    output_path = tmp_path / "reader-failure.log"
    output_fd = _output_fd(output_path)
    reader_failure = OSError("simulated reader failure")
    real_popen = runner.subprocess.Popen

    class FailingPipe:
        def __init__(self, pipe) -> None:
            self._pipe = pipe

        def __iter__(self):
            return self

        def __next__(self):
            raise reader_failure

        def close(self) -> None:
            self._pipe.close()

    def launch_with_failing_pipe(*args, **kwargs):
        process = real_popen(*args, **kwargs)
        process.stdout = FailingPipe(process.stdout)
        return process

    with monkeypatch.context() as patcher:
        patcher.setattr(runner.subprocess, "Popen", launch_with_failing_pipe)

        with pytest.raises(
            RuntimeError,
            match="failed to capture child output",
        ) as caught:
            runner.run_bounded(
                [
                    sys.executable,
                    "-c",
                    "import time; time.sleep(60)",
                    marker,
                ],
                timeout_seconds=0.2,
                heartbeat_seconds=0.05,
                output_fd=output_fd,
                termination_grace_seconds=0.1,
            )

    assert caught.value.__cause__ is reader_failure
    assert os.fstat(output_fd).st_ino == output_path.stat().st_ino
    assert _wait_until_process_exits(marker)


def test_runner_terminates_process_group_on_timeout(
    tmp_path: Path,
) -> None:
    runner = _runner_module()
    marker = f"bounded-runner-{uuid.uuid4().hex}"
    child_pid_path = tmp_path / "child.pid"
    child_code = "import time; time.sleep(60)"
    parent_code = (
        "import pathlib,subprocess,sys,time;"
        f"child=subprocess.Popen([sys.executable,'-c',{child_code!r},"
        f"{marker!r}]);"
        f"pathlib.Path({str(child_pid_path)!r}).write_text(str(child.pid));"
        "print('spawned',flush=True);"
        "time.sleep(60)"
    )

    try:
        result = runner.run_bounded(
            [sys.executable, "-c", parent_code],
            timeout_seconds=0.25,
            heartbeat_seconds=0.05,
            output_fd=_output_fd(tmp_path / "timeout.log"),
            termination_grace_seconds=0.2,
        )

        assert result.timed_out is True
        assert result.term_sent is True
        assert _wait_until_process_exits(marker)
    finally:
        if child_pid_path.exists():
            child_pid = int(child_pid_path.read_text(encoding="utf-8"))
            try:
                os.kill(child_pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


def test_runner_kills_group_when_term_is_ignored(
    tmp_path: Path,
) -> None:
    runner = _runner_module()
    result = runner.run_bounded(
        [
            sys.executable,
            "-c",
            (
                "import signal,time;"
                "signal.signal(signal.SIGTERM,signal.SIG_IGN);"
                "print('ready',flush=True);"
                "time.sleep(60)"
            ),
        ],
        timeout_seconds=0.25,
        heartbeat_seconds=0.05,
        output_fd=_output_fd(tmp_path / "kill.log"),
        termination_grace_seconds=0.1,
    )

    assert result.timed_out is True
    assert result.term_sent is True
    assert result.kill_sent is True


def test_runner_bounds_descendant_after_group_leader_exits(
    tmp_path: Path,
) -> None:
    runner = _runner_module()
    started_at = time.monotonic()

    result = runner.run_bounded(
        [
            sys.executable,
            "-c",
            (
                "import subprocess,sys;"
                "subprocess.Popen([sys.executable,'-c',"
                "'import time;time.sleep(1)']);"
                "print('leader done',flush=True)"
            ),
        ],
        timeout_seconds=0.2,
        heartbeat_seconds=0.05,
        output_fd=_output_fd(tmp_path / "descendant.log"),
        termination_grace_seconds=0.1,
    )

    assert result.timed_out is True
    assert result.term_sent is True
    assert time.monotonic() - started_at < 0.8


@pytest.mark.parametrize(
    "sensitive_argument",
    [
        "GUIDE_LLM_API_KEY=must-not-run",
        "Authorization: Bearer must-not-run",
    ],
)
def test_runner_rejects_sensitive_command_arguments(
    tmp_path: Path,
    sensitive_argument: str,
) -> None:
    runner = _runner_module()
    output_path = tmp_path / "rejected.log"
    output_fd = _output_fd(output_path)

    with pytest.raises(
        runner.UnsafeCommandError,
        match="sensitive command argument",
    ):
        runner.run_bounded(
            [sys.executable, "-c", "pass", sensitive_argument],
            timeout_seconds=2,
            heartbeat_seconds=0.05,
            output_fd=output_fd,
        )

    assert output_path.read_bytes() == b""
    assert os.fstat(output_fd).st_ino == output_path.stat().st_ino


@pytest.mark.parametrize("descriptor_kind", ["closed", "directory", "readonly"])
def test_runner_rejects_invalid_or_readonly_output_fd(
    tmp_path: Path,
    descriptor_kind: str,
) -> None:
    runner = _runner_module()
    if descriptor_kind == "closed":
        descriptor = _output_fd(tmp_path / "closed.log")
        os.close(descriptor)
        _OPEN_OUTPUT_FDS.remove(descriptor)
    elif descriptor_kind == "directory":
        descriptor = os.open(
            tmp_path,
            os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC,
        )
        _OPEN_OUTPUT_FDS.add(descriptor)
    else:
        path = tmp_path / "readonly.log"
        path.write_bytes(b"")
        descriptor = _output_fd(path, flags=os.O_RDONLY)

    with pytest.raises(
        runner.InvalidOutputDescriptorError,
        match="regular writable file",
    ):
        runner.run_bounded(
            [sys.executable, "-c", "print('must not run')"],
            timeout_seconds=2,
            heartbeat_seconds=0.05,
            output_fd=descriptor,
        )


def test_cli_runs_command_after_separator(tmp_path: Path) -> None:
    runner = _runner_module()
    output_path = tmp_path / "cli.log"
    summary_path = tmp_path / "cli.json"

    returncode = runner.main(
        [
            "--timeout-seconds",
            "2",
            "--heartbeat-seconds",
            "0.05",
            "--output",
            str(output_path),
            "--summary",
            str(summary_path),
            "--",
            sys.executable,
            "-c",
            "print('cli')",
        ]
    )

    assert returncode == 0
    assert output_path.read_text(encoding="utf-8") == "cli\n"
    assert stat.S_IMODE(output_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(summary_path.stat().st_mode) == 0o600
    assert json.loads(summary_path.read_text(encoding="utf-8"))[
        "returncode"
    ] == 0


def test_cli_rejects_output_and_summary_replacement_during_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _runner_module()
    output_path = tmp_path / "cli.log"
    summary_path = tmp_path / "cli.json"
    detached_output = tmp_path / "detached.log"
    detached_summary = tmp_path / "detached.json"
    replacement_output = b"replacement output must remain unchanged\n"
    replacement_summary = b'{"replacement":true}\n'

    def replace_paths(*args, **kwargs):
        output_path.rename(detached_output)
        summary_path.rename(detached_summary)
        output_path.write_bytes(replacement_output)
        summary_path.write_bytes(replacement_summary)
        return runner.BoundedCommandResult(
            returncode=0,
            timed_out=False,
            term_sent=False,
            kill_sent=False,
            elapsed_seconds=0.01,
            output_lines=0,
        )

    monkeypatch.setattr(runner, "run_bounded", replace_paths)

    returncode = runner.main(
        [
            "--timeout-seconds",
            "2",
            "--heartbeat-seconds",
            "0.05",
            "--output",
            str(output_path),
            "--summary",
            str(summary_path),
            "--",
            sys.executable,
            "-c",
            "pass",
        ]
    )

    assert returncode == 1
    assert output_path.read_bytes() == replacement_output
    assert summary_path.read_bytes() == replacement_summary
    assert json.loads(detached_summary.read_bytes())["status"] == "failed"


def test_cli_rejects_symlink_output_without_launching_child(
    tmp_path: Path,
) -> None:
    runner = _runner_module()
    target = tmp_path / "attacker-target"
    original = b"attacker target must remain unchanged\n"
    target.write_bytes(original)
    output_path = tmp_path / "cli.log"
    output_path.symlink_to(target)
    summary_path = tmp_path / "cli.json"
    launch_marker = tmp_path / "child-launched"

    returncode = runner.main(
        [
            "--timeout-seconds",
            "2",
            "--heartbeat-seconds",
            "0.05",
            "--output",
            str(output_path),
            "--summary",
            str(summary_path),
            "--",
            sys.executable,
            "-c",
            (
                "from pathlib import Path;"
                f"Path({str(launch_marker)!r}).write_text('launched')"
            ),
        ]
    )

    assert returncode == 2
    assert target.read_bytes() == original
    assert output_path.is_symlink()
    assert not summary_path.exists()
    assert not launch_marker.exists()
