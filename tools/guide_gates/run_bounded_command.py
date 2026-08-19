"""Run a command with heartbeat, timeout, and process-group cleanup."""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
from typing import TextIO

if __package__:
    from tools.guide_gates.private_output_io import (
        InvalidOutputDescriptorError,
        OutputBindingError,
        duplicate_writable_regular_fd,
        open_private_path,
        verify_path_binding,
        write_json_fd,
    )
else:
    from private_output_io import (
        InvalidOutputDescriptorError,
        OutputBindingError,
        duplicate_writable_regular_fd,
        open_private_path,
        verify_path_binding,
        write_json_fd,
    )


class UnsafeCommandError(ValueError):
    """Raised when argv contains a credential-bearing argument."""


@dataclass(frozen=True, slots=True)
class BoundedCommandResult:
    returncode: int
    timed_out: bool
    term_sent: bool
    kill_sent: bool
    elapsed_seconds: float
    output_lines: int


def run_bounded(
    command: Sequence[str],
    *,
    timeout_seconds: float,
    heartbeat_seconds: float,
    output_fd: int,
    cwd: str | Path | None = None,
    env: Mapping[str, str] | None = None,
    termination_grace_seconds: float = 5.0,
) -> BoundedCommandResult:
    normalized_command = _validated_command(command)
    _require_positive("timeout_seconds", timeout_seconds)
    _require_positive("heartbeat_seconds", heartbeat_seconds)
    _require_positive(
        "termination_grace_seconds",
        termination_grace_seconds,
    )

    log_descriptor = duplicate_writable_regular_fd(output_fd)
    try:
        log = os.fdopen(
            log_descriptor,
            "w",
            encoding="utf-8",
            closefd=True,
        )
    except BaseException:
        os.close(log_descriptor)
        raise
    started_at = time.monotonic()
    process: subprocess.Popen[str] | None = None
    reader: threading.Thread | None = None
    output_lines = 0
    output_lock = threading.Lock()
    reader_errors: list[BaseException] = []
    timed_out = False
    term_sent = False
    kill_sent = False
    result: BoundedCommandResult | None = None

    def copy_output(pipe: TextIO) -> None:
        nonlocal output_lines
        try:
            for line in pipe:
                log.write(line)
                log.flush()
                with output_lock:
                    output_lines += 1
        except BaseException as exc:
            reader_errors.append(exc)
        finally:
            pipe.close()

    try:
        process = subprocess.Popen(
            normalized_command,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            start_new_session=True,
            env=env,
            bufsize=1,
        )
        if process.stdout is None:
            raise RuntimeError("child output pipe is unavailable")
        reader = threading.Thread(
            target=copy_output,
            args=(process.stdout,),
            name="bounded-command-output",
            daemon=False,
        )
        reader.start()

        deadline = started_at + timeout_seconds
        next_heartbeat = started_at + heartbeat_seconds
        while True:
            leader_returncode = process.poll()
            group_exists = _process_group_exists(process.pid)
            if leader_returncode is not None and not group_exists:
                break

            now = time.monotonic()
            if now >= deadline:
                timed_out = True
                term_sent = _signal_group(process.pid, signal.SIGTERM)
                if _wait_for_group_exit(
                    process,
                    termination_grace_seconds,
                ):
                    break
                kill_sent = _signal_group(process.pid, signal.SIGKILL)
                process.wait()
                break

            if now >= next_heartbeat:
                with output_lock:
                    observed_lines = output_lines
                elapsed = now - started_at
                print(
                    "heartbeat "
                    f"elapsed={elapsed:.1f} "
                    f"output_lines={observed_lines}",
                    file=sys.stderr,
                    flush=True,
                )
                next_heartbeat = now + heartbeat_seconds

            wait_until = min(deadline, next_heartbeat)
            time.sleep(
                max(
                    0.001,
                    min(
                        0.01,
                        wait_until - time.monotonic(),
                    ),
                )
            )

        returncode = process.wait()
        if reader is not None:
            reader.join()
        if reader_errors:
            raise RuntimeError("failed to capture child output") from (
                reader_errors[0]
            )
        elapsed_seconds = round(time.monotonic() - started_at, 3)
        with output_lock:
            final_output_lines = output_lines
        result = BoundedCommandResult(
            returncode=returncode,
            timed_out=timed_out,
            term_sent=term_sent,
            kill_sent=kill_sent,
            elapsed_seconds=elapsed_seconds,
            output_lines=final_output_lines,
        )
    finally:
        if process is not None and _process_group_exists(process.pid):
            _signal_group(process.pid, signal.SIGTERM)
            if not _wait_for_group_exit(
                process,
                termination_grace_seconds,
            ):
                _signal_group(process.pid, signal.SIGKILL)
                process.wait()
        if reader is not None and reader.is_alive():
            reader.join()
        log.close()

    if result is None:
        raise RuntimeError("bounded command completed without a result")
    return result


def _validated_command(command: Sequence[str]) -> tuple[str, ...]:
    if isinstance(command, (str, bytes)):
        raise TypeError("command must be a sequence of arguments")
    normalized = tuple(command)
    if not normalized or any(not isinstance(item, str) for item in normalized):
        raise ValueError("command must contain string arguments")
    for argument in normalized:
        lowered = argument.lower()
        if (
            "guide_llm_api_key=" in lowered
            or "authorization" in lowered
        ):
            raise UnsafeCommandError(
                "sensitive command argument is not allowed"
            )
    return normalized


def _require_positive(name: str, value: float) -> None:
    if not isinstance(value, (int, float)) or value <= 0:
        raise ValueError(f"{name} must be positive")


def _signal_group(process_group_id: int, requested: signal.Signals) -> bool:
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


def _summary_payload(
    result: BoundedCommandResult | None,
    *,
    failure: BaseException | None = None,
) -> Mapping[str, object]:
    if failure is None:
        if result is None:
            raise RuntimeError("summary requires a result or failure")
        return asdict(result)
    return {
        "failure": {
            "message": str(failure),
            "type": type(failure).__name__,
        },
        "status": "failed",
    }


def _verify_cli_output_bindings(
    *,
    output_path: Path,
    output_fd: int,
    summary_path: Path,
    summary_fd: int,
) -> None:
    verify_path_binding(output_path, output_fd)
    verify_path_binding(summary_path, summary_fd)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run a command with heartbeat and process-group timeout."
        )
    )
    parser.add_argument("--timeout-seconds", type=float, required=True)
    parser.add_argument("--heartbeat-seconds", type=float, required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--summary", required=True)
    parser.add_argument(
        "command",
        nargs=argparse.REMAINDER,
        help="command to run, preceded by --",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    command = tuple(arguments.command)
    if command[:1] == ("--",):
        command = command[1:]

    output_path = Path(arguments.output)
    summary_path = Path(arguments.summary)
    output_fd: int | None = None
    summary_fd: int | None = None
    try:
        output_fd = open_private_path(output_path)
        summary_fd = open_private_path(summary_path)
    except (OSError, TypeError, ValueError):
        if output_fd is not None:
            os.close(output_fd)
        return 2

    try:
        result: BoundedCommandResult | None = None
        failure: BaseException | None = None
        try:
            _verify_cli_output_bindings(
                output_path=output_path,
                output_fd=output_fd,
                summary_path=summary_path,
                summary_fd=summary_fd,
            )
        except BaseException as exc:
            failure = exc

        if failure is None:
            try:
                result = run_bounded(
                    command,
                    timeout_seconds=arguments.timeout_seconds,
                    heartbeat_seconds=arguments.heartbeat_seconds,
                    output_fd=output_fd,
                )
            except BaseException as exc:
                failure = exc

        try:
            _verify_cli_output_bindings(
                output_path=output_path,
                output_fd=output_fd,
                summary_path=summary_path,
                summary_fd=summary_fd,
            )
        except OutputBindingError as exc:
            failure = exc

        if failure is not None:
            try:
                write_json_fd(
                    summary_fd,
                    _summary_payload(None, failure=failure),
                )
                _verify_cli_output_bindings(
                    output_path=output_path,
                    output_fd=output_fd,
                    summary_path=summary_path,
                    summary_fd=summary_fd,
                )
            except BaseException:
                pass
            if isinstance(
                failure,
                (
                    UnsafeCommandError,
                    InvalidOutputDescriptorError,
                    TypeError,
                    ValueError,
                ),
            ):
                return 2
            return 1

        if result is None:
            return 1
        try:
            write_json_fd(summary_fd, _summary_payload(result))
            _verify_cli_output_bindings(
                output_path=output_path,
                output_fd=output_fd,
                summary_path=summary_path,
                summary_fd=summary_fd,
            )
        except BaseException as exc:
            try:
                write_json_fd(
                    summary_fd,
                    _summary_payload(None, failure=exc),
                )
            except BaseException:
                pass
            return 1
        if result.timed_out:
            return 124
        return result.returncode
    finally:
        os.close(summary_fd)
        os.close(output_fd)


if __name__ == "__main__":
    raise SystemExit(main())
