from __future__ import annotations

import argparse
import asyncio
import base64
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
import signal
import stat
import subprocess
import sys
import threading
import time
from threading import Lock
from typing import Any, Iterator, Sequence

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from tools.guide_gates.build_task11_readiness import (
    Task11ReadinessError,
    _candidate_manifest_path_is_valid,
    _manifest_runtime_private_key_paths,
    _read_manifest_once,
    _validated_manifest,
    canonical_payload_sha256,
)
from tools.guide_gates.runtime_auth import (
    RuntimeProofError,
    decode_runtime_private_key,
    encode_runtime_private_key,
    runtime_public_key,
    validate_runtime_public_key,
)
from tools.guide_gates.zero_api_network_guard import (
    ZeroApiNetworkGuard,
    ZeroApiNetworkViolation,
)


_IDENTITY_SCHEMA = "guide-zero-api-runtime-identity-v1"
_CHILD_REPORT_SCHEMA = "guide-zero-api-runtime-child-network-report-v1"
_REPORT_SCHEMA = "guide-zero-api-runtime-network-report-v2"
_CHALLENGE_SCHEMA = "guide-zero-api-runtime-challenge-v1"
_PRIVATE_KEY_SCHEMA = "guide-task11-fixture-runtime-private-key-v1"
_IDENTITY_SIGNATURE_DOMAIN = (
    b"xiaoro-guide-zero-api-runtime-identity-v1\x00"
)
_CHALLENGE_SIGNATURE_DOMAIN = (
    b"xiaoro-guide-zero-api-runtime-challenge-v1\x00"
)
_CHILD_REPORT_SIGNATURE_DOMAIN = (
    b"xiaoro-guide-zero-api-runtime-child-report-v1\x00"
)
_PARENT_REPORT_SIGNATURE_DOMAIN = (
    b"xiaoro-guide-zero-api-runtime-parent-report-v1\x00"
)
_CHALLENGE_PATH = "/__task11_runtime__/challenge"
_SHUTDOWN_PATH = "/__task11_runtime__/shutdown"
_RUNTIME_SANDBOX_IDENTITY_PREFIX = "macos-sandbox-exec-loopback-only:"
_RUNTIME_EXECUTION_SANDBOX_IDENTITY_PREFIX = (
    "macos-sandbox-exec-loopback-only-no-fork:"
)
_RUNTIME_SEATBELT_READY_PREFIX = "XIAORO_RUNTIME_SEATBELT_READY"
_RUNTIME_SEATBELT_CANARY_BEGIN_PREFIX = (
    "XIAORO_RUNTIME_SEATBELT_CANARY_BEGIN"
)
_RUNTIME_SEATBELT_CANARY_END_PREFIX = (
    "XIAORO_RUNTIME_SEATBELT_CANARY_END"
)
_RUNTIME_SEATBELT_BEGIN_PREFIX = "XIAORO_RUNTIME_SEATBELT_BEGIN"
_RUNTIME_SEATBELT_END_PREFIX = "XIAORO_RUNTIME_SEATBELT_END"
_RUNTIME_SEATBELT_DRAIN_PREFIX = "XIAORO_RUNTIME_SEATBELT_DRAIN"
_RUNTIME_SEATBELT_CANARY_PREFIX = "XIAORO_RUNTIME_SEATBELT_CANARY"
_RUNTIME_SANDBOX_ENV = "XIAORO_TASK11_RUNTIME_SANDBOX_SHA256"
_RUNTIME_SANDBOX_NONCE_ENV = "XIAORO_TASK11_RUNTIME_SANDBOX_NONCE"
_RUNTIME_SANDBOX_STAGE_ENV = "XIAORO_TASK11_RUNTIME_SANDBOX_STAGE"
_RUNTIME_CHILD_REPORT_ENV = "XIAORO_TASK11_RUNTIME_CHILD_REPORT"
_RUNTIME_MANIFEST_SHA256_ENV = "XIAORO_TASK11_RUNTIME_MANIFEST_SHA256"
_RUNTIME_CANDIDATE_HEAD_ENV = "XIAORO_TASK11_RUNTIME_CANDIDATE_HEAD"
_RUNTIME_PROTECTED_PAYLOAD_ENV = (
    "XIAORO_TASK11_RUNTIME_PROTECTED_PAYLOAD_SHA256"
)
_RUNTIME_PRIVATE_KEY_ENV = (
    "XIAORO_TASK11_FIXTURE_RUNTIME_PRIVATE_KEY"
)
_SEATBELT_KERNEL_PATH = "/kernel"
_SEATBELT_EXTENSION_PATH = (
    "/System/Library/Extensions/Sandbox.kext/Contents/MacOS/Sandbox"
)
_SEATBELT_ROOT_CANARY_PORT = 9
_SEATBELT_CHILD_CANARY_PORT = 443
_SEATBELT_DRAIN_CANARY_PORT = 53
_DEFAULT_RUNTIME_TIMEOUT_SECONDS = 900.0
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


def _runtime_sandbox_profile(measurement_nonce: str) -> str:
    if _NONCE_PATTERN.fullmatch(measurement_nonce) is None:
        raise ZeroApiRuntimeError("runtime sandbox nonce is invalid")
    return (
        "(version 1)"
        "(allow default)"
        "(deny network-outbound "
        "(with telemetry) "
        f"(with message \"{measurement_nonce}\"))"
        "(allow network-outbound (remote ip \"localhost:*\"))"
        "(allow network-inbound)"
    )


def _runtime_execution_sandbox_profile(
    measurement_nonce: str,
) -> str:
    return (
        _runtime_sandbox_profile(measurement_nonce)
        + "(deny process-fork "
        "(with telemetry) "
        f"(with message \"{measurement_nonce}\"))"
    )


def _build_runtime_sandbox_report(
    *,
    child_report: dict[str, object],
    fixture_runtime_public_key: str,
    sandbox_profile: str,
    runtime_sandbox_profile: str,
    measurement_nonce: str,
    seatbelt_raw: bytes,
    logger_stderr: bytes,
    logger_returncode: int,
    canary_root_pid: int,
    runtime_root_pid: int,
    runtime_process_group_id: int,
    drain_canary_pid: int,
    canary_process_groups_quiescent: bool,
    process_group_quiescent: bool,
) -> dict[str, object]:
    unsigned_child_report = dict(child_report)
    child_signature = unsigned_child_report.pop(
        "runtime_report_signature",
        None,
    )
    _verify_payload_signature(
        public_key=fixture_runtime_public_key,
        domain=_CHILD_REPORT_SIGNATURE_DOMAIN,
        payload=unsigned_child_report,
        signature=child_signature,
    )
    consumed_challenge_sha256s = unsigned_child_report.get(
        "consumed_health_challenge_sha256s"
    )
    if (
        unsigned_child_report.get("schema_version")
        != _CHILD_REPORT_SCHEMA
        or unsigned_child_report.get("measurement")
        != "python-runtime-guard"
        or unsigned_child_report.get("fixture_runtime_public_key")
        != fixture_runtime_public_key
        or not isinstance(consumed_challenge_sha256s, list)
        or not consumed_challenge_sha256s
        or len(consumed_challenge_sha256s)
        != len(set(consumed_challenge_sha256s))
        or any(
            not isinstance(digest, str)
            or _NONCE_PATTERN.fullmatch(digest) is None
            for digest in consumed_challenge_sha256s
        )
    ):
        raise ZeroApiRuntimeError("runtime child network report is invalid")
    expected_profile = _runtime_sandbox_profile(measurement_nonce)
    if not hmac.compare_digest(sandbox_profile, expected_profile):
        raise ZeroApiRuntimeError("runtime sandbox identity is invalid")
    expected_runtime_profile = _runtime_execution_sandbox_profile(
        measurement_nonce
    )
    if not hmac.compare_digest(
        runtime_sandbox_profile,
        expected_runtime_profile,
    ):
        raise ZeroApiRuntimeError(
            "runtime execution sandbox identity is invalid"
        )
    if logger_returncode not in {0, 130, -2}:
        raise ZeroApiRuntimeError(
            "runtime Seatbelt logger exited unexpectedly"
        )
    if process_group_quiescent is not True:
        raise ZeroApiRuntimeError(
            "runtime sandbox process group is not quiescent"
        )
    if canary_process_groups_quiescent is not True:
        raise ZeroApiRuntimeError(
            "runtime canary process groups are not quiescent"
        )
    if any(
        isinstance(value, bool)
        or not isinstance(value, int)
        or value <= 0
        for value in (
            canary_root_pid,
            runtime_root_pid,
            runtime_process_group_id,
            drain_canary_pid,
        )
    ):
        raise ZeroApiRuntimeError(
            "runtime process identity is invalid"
        )
    try:
        stderr_text = logger_stderr.decode("utf-8", errors="strict")
        raw_text = seatbelt_raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ZeroApiRuntimeError(
            "runtime Seatbelt log is not UTF-8"
        ) from exc
    unexpected_stderr = tuple(
        line
        for line in stderr_text.splitlines()
        if line
        and not line.startswith("Filtering the log data using ")
    )
    if unexpected_stderr:
        raise ZeroApiRuntimeError(
            "runtime Seatbelt logger reported an error"
        )

    events: list[dict[str, object]] = []
    for line in raw_text.splitlines():
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ZeroApiRuntimeError(
                "runtime Seatbelt log contains malformed NDJSON"
            ) from exc
        if not isinstance(event, dict):
            raise ZeroApiRuntimeError(
                "runtime Seatbelt log event must be an object"
            )
        events.append(event)
    if any(event.get("eventType") == "lossEvent" for event in events):
        raise ZeroApiRuntimeError("runtime Seatbelt logger lost events")

    ready_marker = (
        f"{_RUNTIME_SEATBELT_READY_PREFIX}:{measurement_nonce}"
    )
    drain_marker = (
        f"{_RUNTIME_SEATBELT_DRAIN_PREFIX}:{measurement_nonce}"
    )
    canary_begin_pattern = re.compile(
        rf"^{_RUNTIME_SEATBELT_CANARY_BEGIN_PREFIX}:"
        rf"{measurement_nonce}:(\d+)$"
    )
    canary_end_pattern = re.compile(
        rf"^{_RUNTIME_SEATBELT_CANARY_END_PREFIX}:"
        rf"{measurement_nonce}:(\d+)$"
    )
    begin_pattern = re.compile(
        rf"^{_RUNTIME_SEATBELT_BEGIN_PREFIX}:"
        rf"{measurement_nonce}:(\d+)$"
    )
    end_pattern = re.compile(
        rf"^{_RUNTIME_SEATBELT_END_PREFIX}:"
        rf"{measurement_nonce}:(\d+)$"
    )
    root_child_pattern = re.compile(
        rf"^{_RUNTIME_SEATBELT_CANARY_PREFIX}:"
        rf"{measurement_nonce}:root_child:(\d+):"
        rf"{_SEATBELT_ROOT_CANARY_PORT}$"
    )
    descendant_pattern = re.compile(
        rf"^{_RUNTIME_SEATBELT_CANARY_PREFIX}:"
        rf"{measurement_nonce}:descendant:(\d+):"
        rf"{_SEATBELT_CHILD_CANARY_PORT}$"
    )
    drain_canary_pattern = re.compile(
        rf"^{_RUNTIME_SEATBELT_CANARY_PREFIX}:"
        rf"{measurement_nonce}:drain:(\d+):"
        rf"{_SEATBELT_DRAIN_CANARY_PORT}$"
    )

    def marker_matches(
        pattern: re.Pattern[str],
    ) -> list[tuple[int, re.Match[str]]]:
        matches: list[tuple[int, re.Match[str]]] = []
        for index, event in enumerate(events):
            if event.get("processImagePath") != "/usr/bin/logger":
                continue
            message = event.get("eventMessage")
            if not isinstance(message, str):
                continue
            match = pattern.fullmatch(message)
            if match is not None:
                matches.append((index, match))
        return matches

    ready_indexes = [
        index
        for index, event in enumerate(events)
        if (
            event.get("processImagePath") == "/usr/bin/logger"
            and event.get("eventMessage") == ready_marker
        )
    ]
    drain_indexes = [
        index
        for index, event in enumerate(events)
        if (
            event.get("processImagePath") == "/usr/bin/logger"
            and event.get("eventMessage") == drain_marker
        )
    ]
    canary_begin = marker_matches(canary_begin_pattern)
    canary_end = marker_matches(canary_end_pattern)
    root_child = marker_matches(root_child_pattern)
    descendant = marker_matches(descendant_pattern)
    begin = marker_matches(begin_pattern)
    end = marker_matches(end_pattern)
    drain_canary = marker_matches(drain_canary_pattern)
    if len(drain_indexes) != 1:
        raise ZeroApiRuntimeError(
            "runtime Seatbelt drain marker set is invalid"
        )
    if (
        not ready_indexes
        or len(canary_begin) != 1
        or len(canary_end) != 1
        or len(begin) != 1
        or len(end) != 1
        or len(root_child) != 1
        or len(descendant) != 1
        or len(drain_canary) != 1
    ):
        raise ZeroApiRuntimeError(
            "runtime Seatbelt marker set is invalid"
        )
    observed_canary_root_pid = int(
        canary_begin[0][1].group(1)
    )
    root_pid = int(begin[0][1].group(1))
    root_child_pid = int(root_child[0][1].group(1))
    descendant_pid = int(descendant[0][1].group(1))
    observed_drain_canary_pid = int(
        drain_canary[0][1].group(1)
    )
    if (
        root_pid != runtime_root_pid
        or runtime_root_pid != runtime_process_group_id
    ):
        raise ZeroApiRuntimeError(
            "runtime process identity is invalid"
        )
    if (
        observed_canary_root_pid != canary_root_pid
        or int(canary_end[0][1].group(1)) != canary_root_pid
        or int(end[0][1].group(1)) != root_pid
        or observed_drain_canary_pid != drain_canary_pid
        or len({
            canary_root_pid,
            root_child_pid,
            descendant_pid,
            runtime_root_pid,
            drain_canary_pid,
        }) != 5
        or not (
            ready_indexes[0]
            < canary_begin[0][0]
            < root_child[0][0]
            < descendant[0][0]
            < canary_end[0][0]
            < begin[0][0]
            < end[0][0]
            < drain_canary[0][0]
            < drain_indexes[0]
        )
    ):
        raise ZeroApiRuntimeError(
            "runtime Seatbelt marker order or identity is invalid"
        )

    denial_pattern = re.compile(
        r"^Sandbox: (?P<process>.+)\((?P<pid>\d+)\) deny\(1\) "
        r"network-outbound remote:\*:(?P<port>\d+)\n"
        rf"{measurement_nonce}$"
    )
    duplicate_denial_pattern = re.compile(
        r"^(?P<count>\d+) duplicate reports? for Sandbox: "
        r"(?P<process>.+)\((?P<pid>\d+)\) deny\(1\) "
        r"network-outbound remote:\*:(?P<port>\d+)\n"
        rf"{measurement_nonce}$"
    )
    denials: list[dict[str, object]] = []
    duplicate_denials: list[dict[str, object]] = []
    for line_number, event in enumerate(events, start=1):
        if (
            event.get("processImagePath") != _SEATBELT_KERNEL_PATH
            or event.get("senderImagePath") != _SEATBELT_EXTENSION_PATH
        ):
            continue
        message = event.get("eventMessage")
        if not isinstance(message, str):
            continue
        match = denial_pattern.fullmatch(message)
        if match is None:
            duplicate_match = duplicate_denial_pattern.fullmatch(
                message
            )
            if duplicate_match is not None:
                duplicate_denials.append(
                    {
                        "count": int(duplicate_match.group("count")),
                        "process": duplicate_match.group("process"),
                        "pid": int(duplicate_match.group("pid")),
                        "port": int(duplicate_match.group("port")),
                        "line_number": line_number,
                    }
                )
                continue
            if measurement_nonce in message:
                raise ZeroApiRuntimeError(
                    "runtime Seatbelt denial event is malformed"
                )
            continue
        denials.append(
            {
                "process": match.group("process"),
                "pid": int(match.group("pid")),
                "port": int(match.group("port")),
                "line_number": line_number,
            }
        )
    root_canaries = [
        item
        for item in denials
        if (
            item["pid"] == root_child_pid
            and item["port"] == _SEATBELT_ROOT_CANARY_PORT
        )
    ]
    descendant_canaries = [
        item
        for item in denials
        if (
            item["pid"] == descendant_pid
            and item["port"] == _SEATBELT_CHILD_CANARY_PORT
        )
    ]
    drain_canaries = [
        item
        for item in denials
        if (
            item["pid"] == drain_canary_pid
            and item["port"] == _SEATBELT_DRAIN_CANARY_PORT
        )
    ]
    if (
        len(root_canaries) != 1
        or len(descendant_canaries) != 1
        or len(drain_canaries) != 1
    ):
        raise ZeroApiRuntimeError(
            "runtime Seatbelt canary denial is missing"
        )
    root_denial_index = int(root_canaries[0]["line_number"]) - 1
    descendant_denial_index = (
        int(descendant_canaries[0]["line_number"]) - 1
    )
    drain_denial_index = int(drain_canaries[0]["line_number"]) - 1
    if not (
        canary_begin[0][0]
        < root_denial_index
        < descendant_denial_index
        < root_child[0][0]
        < descendant[0][0]
        < canary_end[0][0]
        and drain_canary[0][0]
        < drain_denial_index
        < drain_indexes[0]
    ):
        raise ZeroApiRuntimeError(
            "runtime Seatbelt canary delivery order is invalid"
        )
    canary_lines = {
        root_canaries[0]["line_number"],
        descendant_canaries[0]["line_number"],
        drain_canaries[0]["line_number"],
    }
    allowed_duplicate_keys = {
        (root_child_pid, _SEATBELT_ROOT_CANARY_PORT),
        (descendant_pid, _SEATBELT_CHILD_CANARY_PORT),
        (drain_canary_pid, _SEATBELT_DRAIN_CANARY_PORT),
    }
    if any(
        (int(item["pid"]), int(item["port"]))
        not in allowed_duplicate_keys
        for item in duplicate_denials
    ):
        raise ZeroApiRuntimeError(
            "runtime Seatbelt denial event is malformed"
        )
    process_tree_attempts = [
        item
        for item in denials
        if item["line_number"] not in canary_lines
    ]
    if process_tree_attempts:
        raise ZeroApiRuntimeError(
            "runtime Seatbelt observed non-loopback network attempts"
        )

    profile_sha256 = sha256(
        sandbox_profile.encode("utf-8")
    ).hexdigest()
    runtime_profile_sha256 = sha256(
        runtime_sandbox_profile.encode("utf-8")
    ).hexdigest()
    passed = (
        unsigned_child_report.get("passed") is True
        and unsigned_child_report.get("provider_call_count") == 0
        and unsigned_child_report.get("outbound_network_attempt_count") == 0
        and unsigned_child_report.get("attempts") == []
        and unsigned_child_report.get("challenge_consumed") is True
        and unsigned_child_report.get("shutdown_consumed") is True
        and unsigned_child_report.get("shutdown_finalized") is True
        and unsigned_child_report.get("runtime_succeeded") is True
        and unsigned_child_report.get("process_creation_attempt_count") == 0
        and unsigned_child_report.get("process_creation_attempts") == []
    )
    return {
        **unsigned_child_report,
        "schema_version": _REPORT_SCHEMA,
        "measurement": "macos-unified-log-seatbelt-kernel",
        "passed": passed,
        "sandbox_identity": (
            _RUNTIME_SANDBOX_IDENTITY_PREFIX + profile_sha256
        ),
        "sandbox_profile": sandbox_profile,
        "sandbox_profile_sha256": profile_sha256,
        "runtime_sandbox_identity": (
            _RUNTIME_EXECUTION_SANDBOX_IDENTITY_PREFIX
            + runtime_profile_sha256
        ),
        "runtime_sandbox_profile": runtime_sandbox_profile,
        "runtime_sandbox_profile_sha256": runtime_profile_sha256,
        "measurement_nonce": measurement_nonce,
        "seatbelt_raw_ndjson": raw_text,
        "seatbelt_raw_ndjson_sha256": sha256(seatbelt_raw).hexdigest(),
        "seatbelt_raw_byte_count": len(seatbelt_raw),
        "seatbelt_event_count": len(events),
        "seatbelt_canary_denial_count": 3,
        "logger_ready": True,
        "logger_readiness_marker_count": len(ready_indexes),
        "logger_drain_marker_count": len(drain_indexes),
        "logger_loss_event_count": 0,
        "logger_returncode": logger_returncode,
        "process_group_quiescent": True,
        "canary_root_pid": canary_root_pid,
        "root_pid": root_pid,
        "runtime_root_pid": runtime_root_pid,
        "runtime_process_group_id": runtime_process_group_id,
        "drain_canary_pid": drain_canary_pid,
        "root_child_canary_pid": root_child_pid,
        "descendant_canary_pid": descendant_pid,
        "canary_denials": (
            root_canaries[0],
            descendant_canaries[0],
            drain_canaries[0],
        ),
        "canary_process_groups_quiescent": True,
        "process_tree_attempts": process_tree_attempts,
        "duplicate_canary_denial_count": len(duplicate_denials),
        "runtime_process_tree_non_loopback_attempt_count": len(
            process_tree_attempts
        ),
    }


def _runtime_sandbox_context() -> dict[str, str] | None:
    measurement_nonce = os.environ.get(_RUNTIME_SANDBOX_NONCE_ENV)
    marker = os.environ.get(_RUNTIME_SANDBOX_ENV)
    stage = os.environ.get(_RUNTIME_SANDBOX_STAGE_ENV)
    if (
        not isinstance(measurement_nonce, str)
        or _NONCE_PATTERN.fullmatch(measurement_nonce) is None
        or not isinstance(marker, str)
        or stage not in {"canary", "execution"}
    ):
        return None
    sandbox_profile = (
        _runtime_sandbox_profile(measurement_nonce)
        if stage == "canary"
        else _runtime_execution_sandbox_profile(measurement_nonce)
    )
    profile_sha256 = sha256(
        sandbox_profile.encode("utf-8")
    ).hexdigest()
    if not hmac.compare_digest(marker, profile_sha256):
        return None
    return {
        "measurement_nonce": measurement_nonce,
        "stage": stage,
        "sandbox_profile": sandbox_profile,
        "sandbox_profile_sha256": profile_sha256,
    }


def _emit_runtime_seatbelt_marker(marker: str) -> None:
    completed = subprocess.run(
        ["/usr/bin/logger", marker],
        check=False,
        capture_output=True,
    )
    if completed.returncode != 0:
        raise ZeroApiRuntimeError(
            "runtime Seatbelt marker emission failed"
        )


def _run_runtime_seatbelt_canary_child(
    measurement_nonce: str,
    scope: str,
    port: int,
) -> int:
    context = _runtime_sandbox_context()
    if (
        context is None
        or context["measurement_nonce"] != measurement_nonce
        or context["stage"] != "canary"
        or scope not in {"root_child", "descendant", "drain"}
        or port not in {
            _SEATBELT_ROOT_CANARY_PORT,
            _SEATBELT_CHILD_CANARY_PORT,
            _SEATBELT_DRAIN_CANARY_PORT,
        }
        or (
            scope == "root_child"
            and port != _SEATBELT_ROOT_CANARY_PORT
        )
        or (
            scope == "descendant"
            and port != _SEATBELT_CHILD_CANARY_PORT
        )
        or (
            scope == "drain"
            and port != _SEATBELT_DRAIN_CANARY_PORT
        )
    ):
        raise ZeroApiRuntimeError(
            "runtime Seatbelt child context is invalid"
        )
    os.execv(
        "/usr/bin/nc",
        ["nc", "-z", "-G", "1", "192.0.2.1", str(port)],
    )
    raise AssertionError("native runtime Seatbelt canary exec returned")


def _run_denied_native_canary(argv: Sequence[str]) -> None:
    completed = subprocess.run(
        argv,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 1:
        raise ZeroApiRuntimeError(
            "runtime Seatbelt native canary was not denied"
        )


def _run_runtime_seatbelt_canary_branch(
    measurement_nonce: str,
) -> int:
    context = _runtime_sandbox_context()
    if (
        context is None
        or context["measurement_nonce"] != measurement_nonce
        or context["stage"] != "canary"
    ):
        raise ZeroApiRuntimeError(
            "runtime Seatbelt branch context is invalid"
        )
    _run_denied_native_canary(
        (
            sys.executable,
            str(Path(__file__).resolve()),
            "--seatbelt-canary-child",
            measurement_nonce,
            "descendant",
            str(_SEATBELT_CHILD_CANARY_PORT),
        )
    )
    return 0


def _run_runtime_seatbelt_canaries(
    measurement_nonce: str,
) -> int:
    root_pid = os.getpid()
    _run_denied_native_canary(
        (
            sys.executable,
            str(Path(__file__).resolve()),
            "--seatbelt-canary-child",
            measurement_nonce,
            "root_child",
            str(_SEATBELT_ROOT_CANARY_PORT),
        )
    )
    completed = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).resolve()),
            "--seatbelt-canary-branch",
            measurement_nonce,
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0 or completed.stderr:
        raise ZeroApiRuntimeError(
            "runtime Seatbelt descendant canary failed"
        )
    return root_pid


def _require_runtime_canary_start_gate() -> None:
    if sys.stdin.buffer.read() != b"1":
        raise ZeroApiRuntimeError(
            "runtime Seatbelt canary start gate is invalid"
        )


def _seatbelt_log_predicate(measurement_nonce: str) -> str:
    if _NONCE_PATTERN.fullmatch(measurement_nonce) is None:
        raise ZeroApiRuntimeError("runtime sandbox nonce is invalid")
    return f'eventMessage CONTAINS "{measurement_nonce}"'


def _wait_for_runtime_marker_delivery(
    *,
    marker_events: dict[str, threading.Event],
    required_markers: Sequence[str],
    timeout_seconds: float = 10.0,
) -> None:
    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, (int, float))
        or timeout_seconds <= 0
    ):
        raise ZeroApiRuntimeError(
            "runtime Seatbelt marker timeout is invalid"
        )
    missing_events = [
        name
        for name in required_markers
        if name not in marker_events
    ]
    if missing_events:
        raise ZeroApiRuntimeError(
            "runtime Seatbelt marker registry is incomplete: "
            + ", ".join(missing_events)
        )
    deadline = time.monotonic() + timeout_seconds
    for name in required_markers:
        remaining = deadline - time.monotonic()
        if remaining <= 0 or not marker_events[name].wait(remaining):
            missing = [
                marker
                for marker in required_markers
                if not marker_events[marker].is_set()
            ]
            raise ZeroApiRuntimeError(
                "runtime Seatbelt marker delivery is incomplete: "
                + ", ".join(missing)
            )


def _require_process_group_quiescent(
    process_group_id: int,
    *,
    timeout_seconds: float = 5.0,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    while True:
        try:
            os.killpg(process_group_id, 0)
        except ProcessLookupError:
            return
        except PermissionError as exc:
            raise ZeroApiRuntimeError(
                "runtime sandbox process group cannot be inspected"
            ) from exc
        if time.monotonic() >= deadline:
            raise ZeroApiRuntimeError(
                "runtime sandbox process group did not become quiescent"
            )
        time.sleep(0.05)


def _terminate_process_group(process: subprocess.Popen[bytes]) -> None:
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def _run_post_exit_drain_canary(
    *,
    sandbox_profile: str,
    measurement_nonce: str,
    environment: dict[str, str],
    on_started: Callable[[int], None],
) -> int:
    canary = subprocess.Popen(
        [
            "/usr/bin/sandbox-exec",
            "-p",
            sandbox_profile,
            sys.executable,
            str(Path(__file__).resolve()),
            "--seatbelt-canary-child",
            measurement_nonce,
            "drain",
            str(_SEATBELT_DRAIN_CANARY_PORT),
        ],
        env=environment,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    try:
        process_group_id = os.getpgid(canary.pid)
        if process_group_id != canary.pid:
            raise ZeroApiRuntimeError(
                "runtime drain canary process group is invalid"
            )
        on_started(canary.pid)
        if canary.stdin is None:
            raise ZeroApiRuntimeError(
                "runtime drain canary start gate is unavailable"
            )
        canary.stdin.write(b"1")
        canary.stdin.close()
        canary.stdin = None
        try:
            canary.communicate(timeout=10)
        except subprocess.TimeoutExpired as exc:
            raise ZeroApiRuntimeError(
                "runtime drain canary timed out"
            ) from exc
        if canary.returncode != 1:
            raise ZeroApiRuntimeError(
                "runtime drain canary was not denied"
            )
        try:
            _require_process_group_quiescent(process_group_id)
        except ZeroApiRuntimeError:
            _terminate_process_group(canary)
            raise
        return canary.pid
    finally:
        if canary.poll() is None:
            _terminate_process_group(canary)


def _execute_runtime_sandbox_process(
    *,
    argv: tuple[str, ...],
    sandbox_profile: str,
    measurement_nonce: str,
    environment: dict[str, str],
    runtime_timeout_seconds: float,
) -> dict[str, object]:
    if (
        isinstance(runtime_timeout_seconds, bool)
        or not isinstance(runtime_timeout_seconds, (int, float))
        or runtime_timeout_seconds <= 0
    ):
        raise ZeroApiRuntimeError(
            "runtime sandbox timeout is invalid"
        )
    runtime_sandbox_profile = _runtime_execution_sandbox_profile(
        measurement_nonce
    )
    log_process = subprocess.Popen(
        [
            "/usr/bin/log",
            "stream",
            "--style",
            "ndjson",
            "--level",
            "debug",
            "--unreliable",
            "--predicate",
            _seatbelt_log_predicate(measurement_nonce),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if log_process.stdout is None or log_process.stderr is None:
        log_process.kill()
        raise ZeroApiRuntimeError(
            "runtime Seatbelt logger pipes are unavailable"
        )
    raw_chunks: list[bytes] = []
    stderr_chunks: list[bytes] = []
    marker_events = {
        name: threading.Event()
        for name in (
            "ready",
            "canary_begin",
            "root_child",
            "descendant",
            "canary_end",
            "runtime_begin",
            "runtime_end",
            "drain_canary",
            "drain",
        )
    }
    ready_observed = marker_events["ready"]
    preflight_denials_observed = threading.Event()
    kernel_denials: list[tuple[int, int]] = []
    kernel_denial_count = 0
    kernel_denial_lock = threading.Lock()
    ready_marker = (
        f"{_RUNTIME_SEATBELT_READY_PREFIX}:{measurement_nonce}"
    )
    drain_marker = (
        f"{_RUNTIME_SEATBELT_DRAIN_PREFIX}:{measurement_nonce}"
    )
    marker_patterns = {
        "ready": re.compile(rf"^{re.escape(ready_marker)}$"),
        "canary_begin": re.compile(
            rf"^{_RUNTIME_SEATBELT_CANARY_BEGIN_PREFIX}:"
            rf"{measurement_nonce}:\d+$"
        ),
        "root_child": re.compile(
            rf"^{_RUNTIME_SEATBELT_CANARY_PREFIX}:"
            rf"{measurement_nonce}:root_child:\d+:"
            rf"{_SEATBELT_ROOT_CANARY_PORT}$"
        ),
        "descendant": re.compile(
            rf"^{_RUNTIME_SEATBELT_CANARY_PREFIX}:"
            rf"{measurement_nonce}:descendant:\d+:"
            rf"{_SEATBELT_CHILD_CANARY_PORT}$"
        ),
        "canary_end": re.compile(
            rf"^{_RUNTIME_SEATBELT_CANARY_END_PREFIX}:"
            rf"{measurement_nonce}:\d+$"
        ),
        "runtime_begin": re.compile(
            rf"^{_RUNTIME_SEATBELT_BEGIN_PREFIX}:"
            rf"{measurement_nonce}:\d+$"
        ),
        "runtime_end": re.compile(
            rf"^{_RUNTIME_SEATBELT_END_PREFIX}:"
            rf"{measurement_nonce}:\d+$"
        ),
        "drain_canary": re.compile(
            rf"^{_RUNTIME_SEATBELT_CANARY_PREFIX}:"
            rf"{measurement_nonce}:drain:\d+:"
            rf"{_SEATBELT_DRAIN_CANARY_PORT}$"
        ),
        "drain": re.compile(rf"^{re.escape(drain_marker)}$"),
    }

    def read_stdout() -> None:
        nonlocal kernel_denial_count
        for line in iter(log_process.stdout.readline, b""):
            if line.startswith(b"Filtering the log data using "):
                stderr_chunks.append(line)
                continue
            raw_chunks.append(line)
            try:
                event = json.loads(line)
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
            if not isinstance(event, dict):
                continue
            message = event.get("eventMessage")
            process_path = event.get("processImagePath")
            if (
                process_path == "/usr/bin/logger"
                and isinstance(message, str)
            ):
                for marker_name, pattern in marker_patterns.items():
                    if pattern.fullmatch(message) is not None:
                        marker_events[marker_name].set()
            if (
                process_path == _SEATBELT_KERNEL_PATH
                and event.get("senderImagePath")
                == _SEATBELT_EXTENSION_PATH
                and isinstance(message, str)
                and measurement_nonce in message
                and "network-outbound" in message
            ):
                with kernel_denial_lock:
                    kernel_denial_count += 1
                    match = re.search(
                        r"\((\d+)\).*remote:\*:(\d+)\n"
                        + re.escape(measurement_nonce)
                        + r"$",
                        message,
                    )
                    if match is not None:
                        kernel_denials.append(
                            (
                                int(match.group(1)),
                                int(match.group(2)),
                            )
                        )
                    if kernel_denial_count >= 2:
                        preflight_denials_observed.set()

    def read_stderr() -> None:
        for line in iter(log_process.stderr.readline, b""):
            stderr_chunks.append(line)

    stdout_thread = threading.Thread(
        target=read_stdout,
        name="task11-runtime-seatbelt-log-stdout",
    )
    stderr_thread = threading.Thread(
        target=read_stderr,
        name="task11-runtime-seatbelt-log-stderr",
    )
    stdout_thread.start()
    stderr_thread.start()
    canary: subprocess.Popen[bytes] | None = None
    child: subprocess.Popen[bytes] | None = None
    child_stdout = b""
    child_stderr = b""
    child_returncode: int | None = None
    canary_root_pid: int | None = None
    runtime_root_pid: int | None = None
    runtime_process_group_id: int | None = None
    drain_canary_pid: int | None = None
    canary_process_groups_quiescent = False
    process_group_quiescent = False
    try:
        deadline = time.monotonic() + 10
        while not ready_observed.is_set():
            if log_process.poll() is not None:
                raise ZeroApiRuntimeError(
                    "runtime Seatbelt logger exited before readiness"
                )
            _emit_runtime_seatbelt_marker(ready_marker)
            if ready_observed.wait(timeout=0.5):
                break
            if time.monotonic() >= deadline:
                break
        if not ready_observed.is_set():
            raise ZeroApiRuntimeError(
                "runtime Seatbelt readiness marker was not observed"
            )
        canary_environment = {
            **environment,
            _RUNTIME_SANDBOX_STAGE_ENV: "canary",
            _RUNTIME_SANDBOX_ENV: sha256(
                sandbox_profile.encode("utf-8")
            ).hexdigest(),
        }
        canary = subprocess.Popen(
            [
                "/usr/bin/sandbox-exec",
                "-p",
                sandbox_profile,
                sys.executable,
                str(Path(__file__).resolve()),
                "--seatbelt-canary-harness",
                measurement_nonce,
            ],
            env=canary_environment,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        canary_root_pid = canary.pid
        canary_process_group_id = os.getpgid(canary.pid)
        if canary_process_group_id != canary.pid:
            raise ZeroApiRuntimeError(
                "runtime canary process group is invalid"
            )
        _emit_runtime_seatbelt_marker(
            f"{_RUNTIME_SEATBELT_CANARY_BEGIN_PREFIX}:"
            f"{measurement_nonce}:{canary_root_pid}"
        )
        _wait_for_runtime_marker_delivery(
            marker_events=marker_events,
            required_markers=("canary_begin",),
        )
        if canary.stdin is None:
            raise ZeroApiRuntimeError(
                "runtime canary start gate is unavailable"
            )
        canary.stdin.write(b"1")
        canary.stdin.close()
        canary.stdin = None
        try:
            canary_stdout, canary_stderr = canary.communicate(timeout=30)
        except subprocess.TimeoutExpired as exc:
            raise ZeroApiRuntimeError(
                "runtime Seatbelt canary harness timed out"
            ) from exc
        if (
            canary.returncode != 0
            or canary_stdout
            or canary_stderr
        ):
            raise ZeroApiRuntimeError(
                "runtime Seatbelt canary harness failed"
            )
        _require_process_group_quiescent(canary_process_group_id)
        if not preflight_denials_observed.wait(timeout=10):
            raise ZeroApiRuntimeError(
                "runtime Seatbelt preflight denials were not observed"
            )
        with kernel_denial_lock:
            root_child_pids = {
                pid
                for pid, port in kernel_denials
                if port == _SEATBELT_ROOT_CANARY_PORT
            }
            descendant_pids = {
                pid
                for pid, port in kernel_denials
                if port == _SEATBELT_CHILD_CANARY_PORT
            }
        if (
            len(root_child_pids) != 1
            or len(descendant_pids) != 1
        ):
            raise ZeroApiRuntimeError(
                "runtime Seatbelt preflight canary identity is invalid"
            )
        root_child_pid = next(iter(root_child_pids))
        descendant_pid = next(iter(descendant_pids))
        _emit_runtime_seatbelt_marker(
            f"{_RUNTIME_SEATBELT_CANARY_PREFIX}:"
            f"{measurement_nonce}:root_child:{root_child_pid}:"
            f"{_SEATBELT_ROOT_CANARY_PORT}"
        )
        _emit_runtime_seatbelt_marker(
            f"{_RUNTIME_SEATBELT_CANARY_PREFIX}:"
            f"{measurement_nonce}:descendant:{descendant_pid}:"
            f"{_SEATBELT_CHILD_CANARY_PORT}"
        )
        _emit_runtime_seatbelt_marker(
            f"{_RUNTIME_SEATBELT_CANARY_END_PREFIX}:"
            f"{measurement_nonce}:{canary_root_pid}"
        )
        _wait_for_runtime_marker_delivery(
            marker_events=marker_events,
            required_markers=(
                "root_child",
                "descendant",
                "canary_end",
            ),
        )

        runtime_environment = {
            **environment,
            _RUNTIME_SANDBOX_STAGE_ENV: "execution",
            _RUNTIME_SANDBOX_ENV: sha256(
                runtime_sandbox_profile.encode("utf-8")
            ).hexdigest(),
        }
        child = subprocess.Popen(
            [
                "/usr/bin/sandbox-exec",
                "-p",
                runtime_sandbox_profile,
                sys.executable,
                str(Path(__file__).resolve()),
                *argv,
            ],
            env=runtime_environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        runtime_root_pid = child.pid
        runtime_process_group_id = os.getpgid(child.pid)
        if runtime_process_group_id != child.pid:
            raise ZeroApiRuntimeError(
                "runtime sandbox process group identity is invalid"
            )
        _emit_runtime_seatbelt_marker(
            f"{_RUNTIME_SEATBELT_BEGIN_PREFIX}:"
            f"{measurement_nonce}:{runtime_root_pid}"
        )
        _wait_for_runtime_marker_delivery(
            marker_events=marker_events,
            required_markers=("runtime_begin",),
        )
        try:
            child_stdout, child_stderr = child.communicate(
                timeout=runtime_timeout_seconds
            )
        except subprocess.TimeoutExpired as exc:
            raise ZeroApiRuntimeError(
                "runtime sandbox child timed out"
            ) from exc
        child_returncode = child.returncode
        if child_returncode is None:
            raise ZeroApiRuntimeError(
                "runtime sandbox child return code is unavailable"
            )
        _require_process_group_quiescent(runtime_process_group_id)
        process_group_quiescent = True
        _emit_runtime_seatbelt_marker(
            f"{_RUNTIME_SEATBELT_END_PREFIX}:"
            f"{measurement_nonce}:{runtime_root_pid}"
        )
        _wait_for_runtime_marker_delivery(
            marker_events=marker_events,
            required_markers=("runtime_end",),
            timeout_seconds=10 if child_returncode == 0 else 2,
        )
        def mark_drain_canary(pid: int) -> None:
            _emit_runtime_seatbelt_marker(
                f"{_RUNTIME_SEATBELT_CANARY_PREFIX}:"
                f"{measurement_nonce}:drain:{pid}:"
                f"{_SEATBELT_DRAIN_CANARY_PORT}"
            )
            _wait_for_runtime_marker_delivery(
                marker_events=marker_events,
                required_markers=("drain_canary",),
            )

        drain_canary_pid = _run_post_exit_drain_canary(
            sandbox_profile=sandbox_profile,
            measurement_nonce=measurement_nonce,
            environment=canary_environment,
            on_started=mark_drain_canary,
        )
        canary_process_groups_quiescent = True
        deadline = time.monotonic() + 10
        while True:
            with kernel_denial_lock:
                drain_denial_seen = (
                    drain_canary_pid,
                    _SEATBELT_DRAIN_CANARY_PORT,
                ) in kernel_denials
            if drain_denial_seen:
                break
            if time.monotonic() >= deadline:
                raise ZeroApiRuntimeError(
                    "runtime Seatbelt drain canary denial "
                    "was not observed"
                )
            time.sleep(0.05)
        _emit_runtime_seatbelt_marker(drain_marker)
        _wait_for_runtime_marker_delivery(
            marker_events=marker_events,
            required_markers=("drain",),
        )
    finally:
        if canary is not None and canary.poll() is None:
            _terminate_process_group(canary)
        if child is not None and not process_group_quiescent:
            _terminate_process_group(child)
        if log_process.poll() is None:
            log_process.send_signal(signal.SIGINT)
        try:
            logger_returncode = log_process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            log_process.kill()
            logger_returncode = log_process.wait(timeout=5)
        stdout_thread.join(timeout=5)
        stderr_thread.join(timeout=5)
    if stdout_thread.is_alive() or stderr_thread.is_alive():
        raise ZeroApiRuntimeError(
            "runtime Seatbelt logger did not drain cleanly"
        )
    if child is None:
        raise ZeroApiRuntimeError(
            "runtime sandbox child did not start"
        )
    if (
        canary_root_pid is None
        or runtime_root_pid is None
        or runtime_process_group_id is None
        or drain_canary_pid is None
    ):
        raise ZeroApiRuntimeError(
            "runtime sandbox process identity is incomplete"
        )
    return {
        "child_returncode": child_returncode,
        "child_stdout": child_stdout,
        "child_stderr": child_stderr,
        "seatbelt_raw": b"".join(raw_chunks),
        "logger_stderr": b"".join(stderr_chunks),
        "logger_returncode": logger_returncode,
        "canary_root_pid": canary_root_pid,
        "runtime_root_pid": runtime_root_pid,
        "runtime_process_group_id": runtime_process_group_id,
        "drain_canary_pid": drain_canary_pid,
        "canary_process_groups_quiescent": (
            canary_process_groups_quiescent
        ),
        "process_group_quiescent": process_group_quiescent,
    }


def _replace_cli_option(
    arguments: Sequence[str],
    *,
    option: str,
    value: str,
) -> tuple[str, ...]:
    updated = list(arguments)
    try:
        index = updated.index(option)
    except ValueError as exc:
        raise ZeroApiRuntimeError(
            f"runtime argument {option} is missing"
        ) from exc
    if index + 1 >= len(updated):
        raise ZeroApiRuntimeError(
            f"runtime argument {option} has no value"
        )
    updated[index + 1] = value
    return tuple(updated)


def _encode_signature(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _decode_signature(value: object) -> bytes:
    if not isinstance(value, str) or not value:
        raise ZeroApiRuntimeError("runtime signature is invalid")
    try:
        decoded = base64.b64decode(
            value + ("=" * (-len(value) % 4)),
            altchars=b"-_",
            validate=True,
        )
    except (TypeError, ValueError) as exc:
        raise ZeroApiRuntimeError(
            "runtime signature is invalid"
        ) from exc
    if len(decoded) != 64 or _encode_signature(decoded) != value:
        raise ZeroApiRuntimeError("runtime signature is invalid")
    return decoded


def _public_key_bytes(value: object) -> bytes:
    try:
        encoded = validate_runtime_public_key(value)
        return base64.b64decode(
            encoded + ("=" * (-len(encoded) % 4)),
            altchars=b"-_",
            validate=True,
        )
    except (RuntimeProofError, TypeError, ValueError) as exc:
        raise ZeroApiRuntimeError(
            "fixture runtime public key is invalid"
        ) from exc


def _sign_payload(
    *,
    private_key: Ed25519PrivateKey,
    domain: bytes,
    payload: dict[str, object],
) -> str:
    return _encode_signature(
        private_key.sign(domain + _canonical_bytes(payload))
    )


def _verify_payload_signature(
    *,
    public_key: object,
    domain: bytes,
    payload: dict[str, object],
    signature: object,
) -> None:
    try:
        Ed25519PublicKey.from_public_bytes(
            _public_key_bytes(public_key)
        ).verify(
            _decode_signature(signature),
            domain + _canonical_bytes(payload),
        )
    except (InvalidSignature, ValueError) as exc:
        raise ZeroApiRuntimeError(
            "runtime signature is invalid"
        ) from exc


def _validate_runtime_private_key(
    *,
    encoded_private_key: object,
    expected_public_key: object,
) -> Ed25519PrivateKey:
    try:
        private_key = decode_runtime_private_key(encoded_private_key)
        public_key = validate_runtime_public_key(expected_public_key)
        actual_public_key = _encode_signature(
            private_key.public_key().public_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PublicFormat.Raw,
            )
        )
    except (RuntimeProofError, ValueError) as exc:
        raise ZeroApiRuntimeError(
            "fixture runtime private key is invalid"
        ) from exc
    if not hmac.compare_digest(actual_public_key, public_key):
        raise ZeroApiRuntimeError(
            "fixture runtime private key does not match manifest"
        )
    return private_key


def _manifest_runtime_public_keys(
    manifest: dict[str, Any],
) -> tuple[str, str]:
    values = manifest.get("fixture_runtime_public_keys")
    if (
        not isinstance(values, list)
        or len(values) != 2
        or any(not isinstance(value, str) for value in values)
        or len(set(values)) != 2
    ):
        raise ZeroApiRuntimeError(
            "fixture runtime public keys are invalid"
        )
    for value in values:
        try:
            validate_runtime_public_key(value)
        except RuntimeProofError as exc:
            raise ZeroApiRuntimeError(
                "fixture runtime public keys are invalid"
            ) from exc
    return str(values[0]), str(values[1])


def _consume_runtime_private_key_file(
    *,
    path: Path,
    manifest: dict[str, Any],
    expected_manifest_sha256: str,
) -> Ed25519PrivateKey:
    raw_path = path.expanduser()
    if not raw_path.is_absolute() or raw_path.is_symlink():
        raise ZeroApiRuntimeError(
            "fixture runtime private key path is invalid"
        )
    root_value = manifest.get("repository_root")
    try:
        bound_paths = _manifest_runtime_private_key_paths(
            manifest,
            repo_root=Path(str(root_value)).resolve(),
        )
    except (Task11ReadinessError, OSError) as exc:
        raise ZeroApiRuntimeError(
            "fixture runtime private key path is invalid"
        ) from exc
    canonical_path = raw_path.parent.resolve() / raw_path.name
    if canonical_path not in bound_paths:
        raise ZeroApiRuntimeError(
            "fixture runtime private key path is invalid"
        )
    directory_flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    file_flags = (
        os.O_RDWR
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    parent_descriptor: int | None = None
    parent_identity: tuple[int, int] | None = None
    descriptor: int | None = None

    def require_parent_binding() -> None:
        if parent_descriptor is None or parent_identity is None:
            raise ZeroApiRuntimeError(
                "fixture runtime private key parent changed"
            )
        visible_descriptor: int | None = None
        try:
            visible_descriptor = os.open(
                canonical_path.parent,
                directory_flags,
            )
            opened_parent = os.fstat(parent_descriptor)
            visible_parent = os.fstat(visible_descriptor)
        except OSError as exc:
            raise ZeroApiRuntimeError(
                "fixture runtime private key parent changed"
            ) from exc
        finally:
            if visible_descriptor is not None:
                os.close(visible_descriptor)
        if (
            (opened_parent.st_dev, opened_parent.st_ino)
            != parent_identity
            or (visible_parent.st_dev, visible_parent.st_ino)
            != parent_identity
        ):
            raise ZeroApiRuntimeError(
                "fixture runtime private key parent changed"
            )

    def close_descriptors() -> None:
        nonlocal descriptor, parent_descriptor
        if descriptor is not None:
            os.close(descriptor)
            descriptor = None
        if parent_descriptor is not None:
            os.close(parent_descriptor)
            parent_descriptor = None

    try:
        parent_descriptor = os.open(
            canonical_path.parent,
            directory_flags,
        )
        parent_metadata = os.fstat(parent_descriptor)
        parent_identity = (
            parent_metadata.st_dev,
            parent_metadata.st_ino,
        )
        descriptor = os.open(
            canonical_path.name,
            file_flags,
            dir_fd=parent_descriptor,
        )
        metadata = os.fstat(descriptor)
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        raw = b"".join(chunks)
        payload = json.loads(raw)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        close_descriptors()
        raise ZeroApiRuntimeError(
            "fixture runtime private key is invalid"
        ) from exc
    if (
        not stat.S_ISREG(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) != 0o600
        or metadata.st_uid != os.getuid()
        or metadata.st_nlink != 1
        or not isinstance(payload, dict)
        or raw != _canonical_bytes(payload)
        or set(payload)
        != {
            "schema_version",
            "candidate_manifest_sha256",
            "runtime_key_slot",
            "fixture_runtime_public_key",
            "fixture_runtime_private_key",
        }
        or payload.get("schema_version") != _PRIVATE_KEY_SCHEMA
        or payload.get("candidate_manifest_sha256")
        != expected_manifest_sha256
        or type(payload.get("runtime_key_slot")) is not int
        or payload["runtime_key_slot"] not in {1, 2}
    ):
        close_descriptors()
        raise ZeroApiRuntimeError(
            "fixture runtime private key is invalid"
        )
    public_keys = _manifest_runtime_public_keys(manifest)
    runtime_key_slot = int(payload["runtime_key_slot"])
    if (
        payload.get("fixture_runtime_public_key")
        != public_keys[runtime_key_slot - 1]
    ):
        close_descriptors()
        raise ZeroApiRuntimeError(
            "fixture runtime private key is invalid"
        )
    try:
        private_key = _validate_runtime_private_key(
            encoded_private_key=payload.get(
                "fixture_runtime_private_key"
            ),
            expected_public_key=payload.get(
                "fixture_runtime_public_key"
            ),
        )
    except BaseException:
        close_descriptors()
        raise
    try:
        require_parent_binding()
        current = os.stat(
            canonical_path.name,
            dir_fd=parent_descriptor,
            follow_symlinks=False,
        )
        if (
            current.st_dev != metadata.st_dev
            or current.st_ino != metadata.st_ino
            or current.st_nlink != 1
        ):
            raise ZeroApiRuntimeError(
                "fixture runtime private key inode changed"
            )
        os.unlink(
            canonical_path.name,
            dir_fd=parent_descriptor,
        )
        os.fsync(parent_descriptor)
        consumed = os.fstat(descriptor)
        if (
            consumed.st_dev != metadata.st_dev
            or consumed.st_ino != metadata.st_ino
            or consumed.st_nlink != 0
        ):
            raise ZeroApiRuntimeError(
                "fixture runtime private key inode changed"
            )
        os.ftruncate(descriptor, 0)
        os.fsync(descriptor)
        require_parent_binding()
    except OSError as exc:
        raise ZeroApiRuntimeError(
            "fixture runtime private key was not consumed"
        ) from exc
    finally:
        close_descriptors()
    return private_key


def _runtime_private_key(
    *,
    path: Path,
    manifest: dict[str, Any],
    expected_manifest_sha256: str,
) -> Ed25519PrivateKey:
    encoded = os.environ.pop(_RUNTIME_PRIVATE_KEY_ENV, None)
    if encoded is not None:
        if path.exists() or path.is_symlink():
            raise ZeroApiRuntimeError(
                "fixture runtime private key was not consumed by parent"
            )
        try:
            private_key = decode_runtime_private_key(encoded)
        except RuntimeProofError as exc:
            raise ZeroApiRuntimeError(
                "fixture runtime private key is invalid"
            ) from exc
        if runtime_public_key(private_key) not in (
            _manifest_runtime_public_keys(manifest)
        ):
            raise ZeroApiRuntimeError(
                "fixture runtime private key does not match manifest"
            )
        return private_key
    return _consume_runtime_private_key_file(
        path=path,
        manifest=manifest,
        expected_manifest_sha256=expected_manifest_sha256,
    )


def _run_runtime_in_macos_sandbox(
    arguments: Sequence[str],
    *,
    manifest_path: Path,
    expected_manifest_sha256: str,
    runtime_signing_private_key_path: Path,
    network_report: Path,
    runtime_timeout_seconds: float = _DEFAULT_RUNTIME_TIMEOUT_SECONDS,
) -> int:
    if (
        sys.platform != "darwin"
        or not Path("/usr/bin/sandbox-exec").is_file()
    ):
        raise ZeroApiRuntimeError(
            "zero API runtime requires macOS sandbox-exec"
        )
    report_path = network_report.resolve()
    if report_path.exists() or report_path.is_symlink():
        raise ZeroApiRuntimeError("network report already exists")
    manifest, _, candidate_head = _load_candidate_manifest(
        manifest_path.absolute(),
        expected_manifest_sha256=expected_manifest_sha256,
    )
    runtime_private_key = _consume_runtime_private_key_file(
        path=runtime_signing_private_key_path,
        manifest=manifest,
        expected_manifest_sha256=expected_manifest_sha256,
    )
    selected_runtime_public_key = runtime_public_key(
        runtime_private_key
    )
    if selected_runtime_public_key not in _manifest_runtime_public_keys(
        manifest
    ):
        raise ZeroApiRuntimeError(
            "fixture runtime private key does not match manifest"
        )
    manifest_sha256 = expected_manifest_sha256
    measurement_nonce = secrets.token_hex(32)
    sandbox_profile = _runtime_sandbox_profile(measurement_nonce)
    runtime_sandbox_profile = _runtime_execution_sandbox_profile(
        measurement_nonce
    )
    child_report = report_path.with_name(
        f".{report_path.name}.{measurement_nonce}.child.json"
    )
    environment = {
        **os.environ,
        _RUNTIME_SANDBOX_NONCE_ENV: measurement_nonce,
        _RUNTIME_CHILD_REPORT_ENV: str(child_report),
        _RUNTIME_MANIFEST_SHA256_ENV: manifest_sha256,
        _RUNTIME_CANDIDATE_HEAD_ENV: candidate_head,
        _RUNTIME_PROTECTED_PAYLOAD_ENV: str(
            manifest["protected_payload_sha256"]
        ),
        _RUNTIME_PRIVATE_KEY_ENV: encode_runtime_private_key(
            runtime_private_key
        ),
    }
    child_arguments = _replace_cli_option(
        arguments,
        option="--network-report",
        value=str(child_report),
    )
    try:
        capture = _execute_runtime_sandbox_process(
            argv=child_arguments,
            sandbox_profile=sandbox_profile,
            measurement_nonce=measurement_nonce,
            environment=environment,
            runtime_timeout_seconds=runtime_timeout_seconds,
        )
        child_returncode = capture.get("child_returncode")
        child_stderr = capture.get("child_stderr")
        if (
            child_returncode != 0
            or not isinstance(child_stderr, bytes)
            or child_stderr
            or not child_report.is_file()
        ):
            raise ZeroApiRuntimeError(
                "runtime sandbox child failed"
            )
        try:
            child_payload = json.loads(
                child_report.read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError) as exc:
            raise ZeroApiRuntimeError(
                "runtime child network report is invalid"
            ) from exc
        if not isinstance(child_payload, dict):
            raise ZeroApiRuntimeError(
                "runtime child network report is invalid"
            )
        seatbelt_raw = capture.get("seatbelt_raw")
        logger_stderr = capture.get("logger_stderr")
        logger_returncode = capture.get("logger_returncode")
        canary_root_pid = capture.get("canary_root_pid")
        runtime_root_pid = capture.get("runtime_root_pid")
        runtime_process_group_id = capture.get(
            "runtime_process_group_id"
        )
        drain_canary_pid = capture.get("drain_canary_pid")
        canary_process_groups_quiescent = capture.get(
            "canary_process_groups_quiescent"
        )
        process_group_quiescent = capture.get(
            "process_group_quiescent"
        )
        if (
            not isinstance(seatbelt_raw, bytes)
            or not isinstance(logger_stderr, bytes)
            or not isinstance(logger_returncode, int)
            or not isinstance(canary_root_pid, int)
            or isinstance(canary_root_pid, bool)
            or not isinstance(runtime_root_pid, int)
            or isinstance(runtime_root_pid, bool)
            or not isinstance(runtime_process_group_id, int)
            or isinstance(runtime_process_group_id, bool)
            or not isinstance(drain_canary_pid, int)
            or isinstance(drain_canary_pid, bool)
            or canary_process_groups_quiescent is not True
            or process_group_quiescent is not True
        ):
            raise ZeroApiRuntimeError(
                "runtime Seatbelt capture is invalid"
            )
        report = _build_runtime_sandbox_report(
            child_report=child_payload,
            fixture_runtime_public_key=selected_runtime_public_key,
            sandbox_profile=sandbox_profile,
            runtime_sandbox_profile=runtime_sandbox_profile,
            measurement_nonce=measurement_nonce,
            seatbelt_raw=seatbelt_raw,
            logger_stderr=logger_stderr,
            logger_returncode=logger_returncode,
            canary_root_pid=canary_root_pid,
            runtime_root_pid=runtime_root_pid,
            runtime_process_group_id=runtime_process_group_id,
            drain_canary_pid=drain_canary_pid,
            canary_process_groups_quiescent=(
                canary_process_groups_quiescent
            ),
            process_group_quiescent=process_group_quiescent,
        )
        report["runtime_report_signature"] = _sign_payload(
            private_key=runtime_private_key,
            domain=_PARENT_REPORT_SIGNATURE_DOMAIN,
            payload=report,
        )
        _write_json_atomically(report_path, report)
        return 0
    finally:
        child_report.unlink(missing_ok=True)


class RuntimeChallengeAuthority:
    def __init__(
        self,
        *,
        runtime_identity_sha256: str,
        runtime_private_key: Ed25519PrivateKey,
        runtime_public_key: str,
        shutdown_token: str | None = None,
        shutdown_callback: Callable[[], None] | None = None,
    ) -> None:
        if not re.fullmatch(r"[0-9a-f]{64}", runtime_identity_sha256):
            raise ZeroApiRuntimeError(
                "runtime identity digest is invalid"
            )
        self._runtime_identity_sha256 = runtime_identity_sha256
        self._runtime_private_key = runtime_private_key
        self._runtime_public_key = validate_runtime_public_key(
            runtime_public_key
        )
        self._lock = Lock()
        self._issued: dict[str, dict[str, str]] = {}
        self._consumed: set[str] = set()
        self._consumed_challenge_sha256s: list[str] = []
        self._shutdown_token = shutdown_token
        self._shutdown_callback = shutdown_callback
        self._shutdown_consumed = False

    @property
    def challenge_consumed(self) -> bool:
        with self._lock:
            return bool(self._consumed)

    @property
    def consumed_health_challenge_sha256s(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(self._consumed_challenge_sha256s)

    @property
    def shutdown_consumed(self) -> bool:
        with self._lock:
            return self._shutdown_consumed

    def issue(self) -> dict[str, str]:
        challenge = secrets.token_hex(32)
        unsigned = {
            "schema_version": _CHALLENGE_SCHEMA,
            "runtime_identity_sha256": self._runtime_identity_sha256,
            "challenge": challenge,
        }
        signed = {
            **unsigned,
            "challenge_sha256": sha256(
                _canonical_bytes(unsigned)
            ).hexdigest(),
        }
        payload = {
            **signed,
            "challenge_signature": _sign_payload(
                private_key=self._runtime_private_key,
                domain=_CHALLENGE_SIGNATURE_DOMAIN,
                payload=signed,
            ),
        }
        with self._lock:
            self._issued[challenge] = payload
        return dict(payload)

    def consume(self, challenge: object) -> dict[str, str]:
        if not isinstance(challenge, str):
            raise ZeroApiRuntimeError(
                "runtime health challenge is invalid"
            )
        with self._lock:
            if challenge in self._consumed:
                raise ZeroApiRuntimeError(
                    "runtime health challenge already consumed"
                )
            payload = self._issued.pop(challenge, None)
            if payload is None:
                raise ZeroApiRuntimeError(
                    "runtime health challenge is unknown"
                )
            self._consumed.add(challenge)
            self._consumed_challenge_sha256s.append(
                payload["challenge_sha256"]
            )
        return dict(payload)

    def bind_shutdown(self, callback: Callable[[], None]) -> None:
        with self._lock:
            if self._shutdown_callback is not None:
                raise ZeroApiRuntimeError(
                    "runtime shutdown callback is already bound"
                )
            self._shutdown_callback = callback

    def shutdown(self, token: object) -> None:
        with self._lock:
            if self._shutdown_consumed:
                raise ZeroApiRuntimeError(
                    "runtime shutdown token already consumed"
                )
            if (
                not isinstance(token, str)
                or not isinstance(self._shutdown_token, str)
                or not hmac.compare_digest(token, self._shutdown_token)
                or self._shutdown_callback is None
            ):
                raise ZeroApiRuntimeError(
                    "runtime shutdown token is invalid"
                )
            self._shutdown_consumed = True
            callback = self._shutdown_callback
        callback()


class RuntimeChallengeApplication:
    def __init__(
        self,
        application: object,
        *,
        runtime_identity_sha256: str,
        runtime_private_key: Ed25519PrivateKey,
        runtime_public_key: str,
        shutdown_token: str | None = None,
    ) -> None:
        self._application = application
        self._authority = RuntimeChallengeAuthority(
            runtime_identity_sha256=runtime_identity_sha256,
            runtime_private_key=runtime_private_key,
            runtime_public_key=runtime_public_key,
            shutdown_token=shutdown_token,
        )

    @property
    def challenge_consumed(self) -> bool:
        return self._authority.challenge_consumed

    @property
    def consumed_health_challenge_sha256s(self) -> tuple[str, ...]:
        return self._authority.consumed_health_challenge_sha256s

    @property
    def shutdown_consumed(self) -> bool:
        return self._authority.shutdown_consumed

    def bind_shutdown(self, callback: Callable[[], None]) -> None:
        self._authority.bind_shutdown(callback)

    async def __call__(
        self,
        scope: dict[str, Any],
        receive: Callable[[], Any],
        send: Callable[[dict[str, Any]], Any],
    ) -> None:
        if (
            scope.get("type") != "http"
            or scope.get("path")
            not in {_CHALLENGE_PATH, _SHUTDOWN_PATH}
        ):
            await self._application(scope, receive, send)  # type: ignore[misc]
            return
        client = scope.get("client")
        if (
            not isinstance(client, (tuple, list))
            or not client
            or not _is_loopback_host(client[0])
        ):
            await self._send_json(send, 403, {"error": "loopback_required"})
            return
        method = scope.get("method")
        path = scope.get("path")
        if path == _CHALLENGE_PATH and method == "GET":
            await self._send_json(send, 200, self._authority.issue())
            return
        if method != "POST":
            await self._send_json(send, 405, {"error": "method_not_allowed"})
            return
        body = bytearray()
        more_body = True
        while more_body:
            message = await receive()
            if message.get("type") != "http.request":
                continue
            body.extend(message.get("body", b""))
            more_body = bool(message.get("more_body", False))
        try:
            payload = json.loads(bytes(body))
            if path == _CHALLENGE_PATH:
                response_payload: dict[str, object] = (
                    self._authority.consume(payload.get("challenge"))
                )
            else:
                self._authority.shutdown(payload.get("runtime_nonce"))
                response_payload = {"status": "stopping"}
        except (
            json.JSONDecodeError,
            AttributeError,
            ZeroApiRuntimeError,
        ) as exc:
            await self._send_json(send, 409, {"error": str(exc)})
            return
        await self._send_json(send, 200, response_payload)

    @staticmethod
    async def _send_json(
        send: Callable[[dict[str, Any]], Any],
        status: int,
        payload: dict[str, object],
    ) -> None:
        content = json.dumps(
            payload,
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


class _RuntimeLifecycle:
    def __init__(self) -> None:
        self.runtime_started = False
        self.ready_identity_written = False
        self.challenge_consumed = False
        self.shutdown_consumed = False
        self.shutdown_finalized = False
        self.runtime_succeeded = False
        self.candidate_manifest_sha256: str | None = None
        self.runtime_identity_sha256: str | None = None
        self.consumed_health_challenge_sha256s: tuple[str, ...] = ()


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
        runtime_private_key: Ed25519PrivateKey,
        runtime_public_key: str,
    ) -> None:
        super().__init__()
        self._lifecycle = lifecycle
        self._process_guard = process_guard
        self._runtime_private_key = runtime_private_key
        self._runtime_public_key = runtime_public_key

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
        unsigned_report = {
            **measured,
            "schema_version": _CHILD_REPORT_SCHEMA,
            "measurement": "python-runtime-guard",
            "fixture_runtime_public_key": self._runtime_public_key,
            "passed": passed,
            "runtime_started": self._lifecycle.runtime_started,
            "ready_identity_written": (
                self._lifecycle.ready_identity_written
            ),
            "challenge_consumed": (
                self._lifecycle.challenge_consumed
            ),
            "consumed_health_challenge_sha256s": list(
                self._lifecycle.consumed_health_challenge_sha256s
            ),
            "shutdown_consumed": (
                self._lifecycle.shutdown_consumed
            ),
            "shutdown_finalized": (
                self._lifecycle.shutdown_finalized
            ),
            "runtime_succeeded": self._lifecycle.runtime_succeeded,
            "process_creation_attempt_count": process_attempts,
            "process_creation_attempts": (
                self._process_guard.attempts
            ),
            "candidate_manifest_sha256": (
                self._lifecycle.candidate_manifest_sha256
            ),
            "runtime_identity_sha256": (
                self._lifecycle.runtime_identity_sha256
            ),
        }
        return {
            **unsigned_report,
            "runtime_report_signature": _sign_payload(
                private_key=self._runtime_private_key,
                domain=_CHILD_REPORT_SIGNATURE_DOMAIN,
                payload=unsigned_report,
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
    try:
        head = (_git_directory(root) / "HEAD").read_text(
            encoding="ascii"
        ).strip()
    except OSError as exc:
        raise ZeroApiRuntimeError(
            "candidate repository HEAD is unavailable"
        ) from exc
    if _REVISION_PATTERN.fullmatch(head):
        return head
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "--verify", "HEAD"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ZeroApiRuntimeError(
            "candidate repository HEAD is unavailable"
        ) from exc
    revision = completed.stdout.strip()
    if not _REVISION_PATTERN.fullmatch(revision):
        raise ZeroApiRuntimeError(
            "candidate repository HEAD is invalid"
        )
    return revision


def _load_candidate_manifest(
    manifest_path: Path,
    *,
    expected_manifest_sha256: str,
) -> tuple[dict[str, Any], Path, str]:
    try:
        manifest, root = _validated_manifest(
            manifest_path,
            expected_manifest_sha256=expected_manifest_sha256,
        )
    except Task11ReadinessError as exc:
        raise ZeroApiRuntimeError(str(exc)) from exc
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


def _load_parent_attested_candidate_manifest(
    manifest_path: Path,
    *,
    expected_manifest_sha256: str,
) -> tuple[dict[str, Any], Path, str]:
    parent_manifest_sha256 = os.environ.get(
        _RUNTIME_MANIFEST_SHA256_ENV
    )
    expected_head = os.environ.get(_RUNTIME_CANDIDATE_HEAD_ENV)
    expected_payload_sha256 = os.environ.get(
        _RUNTIME_PROTECTED_PAYLOAD_ENV
    )
    try:
        manifest, raw = _read_manifest_once(manifest_path)
    except Task11ReadinessError as exc:
        raise ZeroApiRuntimeError(
            str(exc)
        ) from exc
    protected_paths = manifest.get("protected_paths")
    if not (
        isinstance(expected_manifest_sha256, str)
        and _NONCE_PATTERN.fullmatch(expected_manifest_sha256) is not None
        and expected_manifest_sha256
        == parent_manifest_sha256
        and _REVISION_PATTERN.fullmatch(str(expected_head)) is not None
        and isinstance(expected_payload_sha256, str)
        and _NONCE_PATTERN.fullmatch(expected_payload_sha256) is not None
        and sha256(raw).hexdigest() == expected_manifest_sha256
        and manifest.get("candidate_head") == expected_head
        and manifest.get("candidate_payload_sha256")
        == expected_payload_sha256
        and manifest.get("protected_payload_sha256")
        == expected_payload_sha256
        and isinstance(protected_paths, list)
        and all(isinstance(path, str) for path in protected_paths)
    ):
        raise ZeroApiRuntimeError(
            "parent-attested candidate manifest is invalid"
        )
    root = next(
        (
            candidate
            for candidate in manifest_path.parents
            if (
                (candidate / ".git").exists()
                and all(
                    (candidate / path).is_file()
                    for path in protected_paths
                )
            )
        ),
        None,
    )
    repair_epoch = manifest.get("repair_epoch")
    if (
        root is None
        or type(repair_epoch) is not int
        or not _candidate_manifest_path_is_valid(
            manifest_path,
            root=root,
            repair_epoch=repair_epoch,
            plan_revision=manifest.get("plan_revision"),
        )
        or canonical_payload_sha256(root, protected_paths)
        != expected_payload_sha256
    ):
        raise ZeroApiRuntimeError("protected payload drift")
    return manifest, root, str(expected_head)


def _identity_digest(payload: dict[str, object]) -> str:
    unsigned = dict(payload)
    unsigned.pop("identity_sha256", None)
    unsigned.pop("identity_signature", None)
    return sha256(_canonical_bytes(unsigned)).hexdigest()


def _build_runtime_identity(
    *,
    manifest_path: Path,
    manifest: dict[str, Any],
    expected_manifest_sha256: str,
    code_revision: str,
    host: str,
    port: int,
    state_dir: Path,
    runtime_private_key: Ed25519PrivateKey,
    runtime_public_key: str,
) -> dict[str, object]:
    identity: dict[str, object] = {
        "schema_version": _IDENTITY_SCHEMA,
        "candidate_manifest_path": str(manifest_path.resolve()),
        "candidate_manifest_sha256": expected_manifest_sha256,
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
        "runtime_public_key": runtime_public_key,
    }
    identity["identity_sha256"] = _identity_digest(identity)
    identity["identity_signature"] = _sign_payload(
        private_key=runtime_private_key,
        domain=_IDENTITY_SIGNATURE_DOMAIN,
        payload=identity,
    )
    return identity


def verify_runtime_identity(
    *,
    identity_path: str | Path,
    manifest_path: str | Path,
    expected_manifest_sha256: str,
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
            manifest_file,
            expected_manifest_sha256=expected_manifest_sha256,
        )
        process_identity = identity.get("process_identity")
        runtime_nonce = identity.get("runtime_nonce")
        identity_sha256 = identity.get("identity_sha256")
        identity_signature = identity.get("identity_signature")
        signed_identity = dict(identity)
        signed_identity.pop("identity_signature", None)
        _verify_payload_signature(
            public_key=identity.get("runtime_public_key"),
            domain=_IDENTITY_SIGNATURE_DOMAIN,
            payload=signed_identity,
            signature=identity_signature,
        )
        valid = (
            identity.get("schema_version") == _IDENTITY_SCHEMA
            and identity.get("candidate_manifest_path")
            == str(manifest_file.resolve())
            and identity.get("candidate_manifest_sha256")
            == expected_manifest_sha256
            and identity.get("plan_revision")
            == manifest["plan_revision"]
            and identity.get("code_revision") == code_revision
            and identity.get("protected_payload_sha256")
            == manifest["protected_payload_sha256"]
            and identity.get("runtime_public_key")
            in _manifest_runtime_public_keys(manifest)
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


def verify_runtime_challenge(
    *,
    challenge: dict[str, object],
    runtime_identity_sha256: str,
    runtime_public_key: str,
) -> dict[str, object]:
    signed = dict(challenge)
    signature = signed.pop("challenge_signature", None)
    unsigned = {
        "schema_version": signed.get("schema_version"),
        "runtime_identity_sha256": signed.get(
            "runtime_identity_sha256"
        ),
        "challenge": signed.get("challenge"),
    }
    challenge_sha256 = signed.get("challenge_sha256")
    if (
        set(challenge)
        != {
            "schema_version",
            "runtime_identity_sha256",
            "challenge",
            "challenge_sha256",
            "challenge_signature",
        }
        or unsigned["schema_version"] != _CHALLENGE_SCHEMA
        or unsigned["runtime_identity_sha256"]
        != runtime_identity_sha256
        or not isinstance(unsigned["challenge"], str)
        or _NONCE_PATTERN.fullmatch(unsigned["challenge"]) is None
        or unsigned["challenge"] == "0" * 64
        or not isinstance(challenge_sha256, str)
        or not hmac.compare_digest(
            challenge_sha256,
            sha256(_canonical_bytes(unsigned)).hexdigest(),
        )
    ):
        raise ZeroApiRuntimeError(
            "runtime health challenge is invalid"
        )
    _verify_payload_signature(
        public_key=runtime_public_key,
        domain=_CHALLENGE_SIGNATURE_DOMAIN,
        payload=signed,
        signature=signature,
    )
    return dict(challenge)


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
        log_level="critical",
        access_log=False,
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
    expected_manifest_sha256: str,
    runtime_signing_private_key: str | Path,
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
    manifest_file = Path(manifest_path).absolute()
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
    network_guard: _RuntimeNetworkGuard | None = None
    identity: dict[str, object] | None = None
    challenge_application: RuntimeChallengeApplication | None = None
    failure: BaseException | None = None
    guard_installed = False
    process_guard_installed = False

    try:
        sandbox_context = _runtime_sandbox_context()
        manifest, _, code_revision = (
            _load_parent_attested_candidate_manifest(
                manifest_file,
                expected_manifest_sha256=expected_manifest_sha256,
            )
            if (
                sandbox_context is not None
                and sandbox_context["stage"] == "execution"
            )
            else _load_candidate_manifest(
                manifest_file,
                expected_manifest_sha256=expected_manifest_sha256,
            )
        )
        runtime_private_key = _runtime_private_key(
            path=Path(runtime_signing_private_key),
            manifest=manifest,
            expected_manifest_sha256=expected_manifest_sha256,
        )
        selected_runtime_public_key = runtime_public_key(
            runtime_private_key
        )
        if selected_runtime_public_key not in (
            _manifest_runtime_public_keys(manifest)
        ):
            raise ZeroApiRuntimeError(
                "fixture runtime private key does not match manifest"
            )
        network_guard = _RuntimeNetworkGuard(
            lifecycle=lifecycle,
            process_guard=process_guard,
            runtime_private_key=runtime_private_key,
            runtime_public_key=selected_runtime_public_key,
        )
        lifecycle.candidate_manifest_sha256 = (
            expected_manifest_sha256
        )
        network_guard.install()
        guard_installed = True
        process_guard.install()
        process_guard_installed = True
        with _runtime_environment(resolved_state_dir):
            resolved_state_dir.mkdir(parents=True, exist_ok=True)
            identity = _build_runtime_identity(
                manifest_path=manifest_file,
                manifest=manifest,
                expected_manifest_sha256=expected_manifest_sha256,
                code_revision=code_revision,
                host=host,
                port=port,
                state_dir=resolved_state_dir,
                runtime_private_key=runtime_private_key,
                runtime_public_key=selected_runtime_public_key,
            )

            def write_ready_identity() -> None:
                assert identity is not None
                _write_json_atomically(ready_path, identity)
                lifecycle.ready_identity_written = True
                lifecycle.runtime_identity_sha256 = sha256(
                    ready_path.read_bytes()
                ).hexdigest()

            application = application_loader()
            challenge_application = RuntimeChallengeApplication(
                application,
                runtime_identity_sha256=sha256(
                    _canonical_bytes(identity)
                ).hexdigest(),
                runtime_private_key=runtime_private_key,
                runtime_public_key=selected_runtime_public_key,
                shutdown_token=str(identity["runtime_nonce"]),
            )
            server = server_factory(challenge_application, host, port)
            challenge_application.bind_shutdown(
                lambda: setattr(server, "should_exit", True)
            )
            asyncio.run(
                _serve_until_shutdown(
                    server=server,
                    on_started=write_ready_identity,
                    lifecycle=lifecycle,
                )
            )
            lifecycle.challenge_consumed = (
                challenge_application.challenge_consumed
            )
            lifecycle.consumed_health_challenge_sha256s = (
                challenge_application.consumed_health_challenge_sha256s
            )
            lifecycle.shutdown_consumed = (
                challenge_application.shutdown_consumed
            )
            if not lifecycle.challenge_consumed:
                raise ZeroApiRuntimeError(
                    "runtime challenge was not consumed"
                )
            if not lifecycle.shutdown_consumed:
                raise ZeroApiRuntimeError(
                    "runtime shutdown was not consumed"
                )
            if (
                network_guard is None
                or network_guard.provider_call_count != 0
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
        if challenge_application is not None:
            lifecycle.challenge_consumed = (
                challenge_application.challenge_consumed
            )
            lifecycle.consumed_health_challenge_sha256s = (
                challenge_application.consumed_health_challenge_sha256s
            )
            lifecycle.shutdown_consumed = (
                challenge_application.shutdown_consumed
            )
        if process_guard_installed:
            process_guard.uninstall()
        if guard_installed and network_guard is not None:
            network_guard.uninstall()
        lifecycle.shutdown_finalized = lifecycle.shutdown_consumed
        if failure is not None:
            try:
                ready_path.unlink(missing_ok=True)
            except OSError:
                pass
            lifecycle.ready_identity_written = False
            lifecycle.runtime_identity_sha256 = None
        if network_guard is not None:
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
    parser.add_argument(
        "--expected-manifest-sha256",
        required=True,
    )
    parser.add_argument(
        "--runtime-signing-private-key",
        type=Path,
        required=True,
    )
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--ready-file", type=Path, required=True)
    parser.add_argument("--network-report", type=Path, required=True)
    parser.add_argument(
        "--max-runtime-seconds",
        type=float,
        default=_DEFAULT_RUNTIME_TIMEOUT_SECONDS,
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments[:1] == ["--seatbelt-canary-child"]:
        if len(arguments) != 4:
            raise SystemExit(
                "runtime Seatbelt canary child arguments are invalid"
            )
        try:
            port = int(arguments[3])
        except ValueError as exc:
            raise SystemExit(
                "runtime Seatbelt canary child port is invalid"
            ) from exc
        if arguments[2] == "drain":
            _require_runtime_canary_start_gate()
        return _run_runtime_seatbelt_canary_child(
            arguments[1],
            arguments[2],
            port,
        )
    if arguments[:1] == ["--seatbelt-canary-branch"]:
        if len(arguments) != 2:
            raise SystemExit(
                "runtime Seatbelt canary branch arguments are invalid"
            )
        return _run_runtime_seatbelt_canary_branch(arguments[1])
    if arguments[:1] == ["--seatbelt-canary-harness"]:
        if len(arguments) != 2:
            raise SystemExit(
                "runtime Seatbelt canary harness arguments are invalid"
            )
        context = _runtime_sandbox_context()
        if (
            context is None
            or context["stage"] != "canary"
            or context["measurement_nonce"] != arguments[1]
        ):
            raise ZeroApiRuntimeError(
                "runtime Seatbelt canary harness context is invalid"
            )
        _require_runtime_canary_start_gate()
        _run_runtime_seatbelt_canaries(arguments[1])
        return 0

    args = _parser().parse_args(arguments)
    if args.max_runtime_seconds <= 0:
        raise ZeroApiRuntimeError(
            "runtime sandbox timeout is invalid"
        )
    sandbox_context = _runtime_sandbox_context()
    if sandbox_context is None:
        return _run_runtime_in_macos_sandbox(
            arguments,
            manifest_path=args.manifest,
            expected_manifest_sha256=(
                args.expected_manifest_sha256
            ),
            runtime_signing_private_key_path=(
                args.runtime_signing_private_key
            ),
            network_report=args.network_report,
            runtime_timeout_seconds=args.max_runtime_seconds,
        )
    if sandbox_context["stage"] != "execution":
        raise ZeroApiRuntimeError(
            "runtime sandbox stage is invalid"
        )
    identity = run_zero_api_runtime(
        manifest_path=args.manifest,
        expected_manifest_sha256=args.expected_manifest_sha256,
        runtime_signing_private_key=(
            args.runtime_signing_private_key
        ),
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
    "RuntimeChallengeApplication",
    "RuntimeChallengeAuthority",
    "ZeroApiRuntimeError",
    "ZeroApiRuntimeViolation",
    "run_zero_api_runtime",
    "verify_runtime_challenge",
    "verify_runtime_identity",
]
