from __future__ import annotations

import json
import multiprocessing
import os
import socket
import subprocess
import sys

import httpx
import pytest

import tools.guide_gates.zero_api_network_guard as network_guard_module
from app.guide.adapters.llm.provider_common import OpenAIJsonClient
from tools.guide_gates.zero_api_network_guard import (
    ZeroApiNetworkGuard,
    ZeroApiNetworkViolation,
)


def test_zero_api_guard_rejects_non_loopback_connection() -> None:
    guard = ZeroApiNetworkGuard()

    with guard, pytest.raises(
        ZeroApiNetworkViolation,
        match="non-loopback DNS",
    ):
        socket.getaddrinfo("example.com", 443)

    assert guard.outbound_network_attempt_count == 1
    assert guard.provider_call_count == 0


def test_zero_api_guard_counts_provider_boundary_attempt() -> None:
    client = OpenAIJsonClient(
        api_key="not-a-real-key",
        base_url="https://api.deepseek.com",
        timeout_seconds=1.0,
        transport=None,
    )
    guard = ZeroApiNetworkGuard()
    try:
        with guard, pytest.raises(
            ZeroApiNetworkViolation,
            match="provider call",
        ):
            client.request({"model": "never-sent"})
    finally:
        client.close()

    assert guard.provider_call_count == 1
    assert guard.outbound_network_attempt_count == 1


def test_zero_api_guard_allows_mock_http_transport() -> None:
    client = OpenAIJsonClient(
        api_key="not-a-real-key",
        base_url="https://api.deepseek.com",
        timeout_seconds=1.0,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                request=request,
                json={
                    "choices": [
                        {"message": {"content": "{}"}},
                    ],
                    "usage": {},
                },
            )
        ),
    )
    guard = ZeroApiNetworkGuard()
    try:
        with guard:
            completion = client.request({"model": "mock"})
    finally:
        client.close()

    assert completion.content == "{}"
    assert guard.provider_call_count == 0
    assert guard.outbound_network_attempt_count == 0


@pytest.mark.parametrize(
    "command",
    (
        ("/usr/bin/curl", "--version"),
        (
            sys.executable,
            "-c",
            "pass",
        ),
    ),
)
def test_zero_api_guard_rejects_subprocess_escape(
    command: tuple[str, ...],
) -> None:
    guard = ZeroApiNetworkGuard()

    with guard, pytest.raises(
        ZeroApiNetworkViolation,
        match="process creation is forbidden",
    ):
        subprocess.run(command, check=False)

    assert guard.process_creation_attempt_count == 1
    assert guard.process_creation_attempts[0]["kind"] == (
        "subprocess.Popen"
    )


def test_zero_api_guard_rejects_multiprocessing_escape() -> None:
    process = multiprocessing.Process(target=lambda: None)
    guard = ZeroApiNetworkGuard()

    with guard, pytest.raises(
        ZeroApiNetworkViolation,
        match="process creation is forbidden",
    ):
        process.start()

    assert guard.process_creation_attempt_count == 1
    assert guard.process_creation_attempts[0]["kind"] == (
        "multiprocessing.Process.start"
    )


def test_zero_api_guard_rejects_direct_os_process_escape() -> None:
    guard = ZeroApiNetworkGuard()

    with guard, pytest.raises(
        ZeroApiNetworkViolation,
        match="process creation is forbidden",
    ):
        os.posix_spawn("/usr/bin/true", ("/usr/bin/true",), {})

    assert guard.process_creation_attempt_count == 1
    assert guard.process_creation_attempts[0]["kind"] == "os.posix_spawn"


def test_zero_api_guard_allows_children_only_with_kernel_sandbox(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        network_guard_module,
        "_kernel_network_sandbox_active",
        lambda: True,
    )
    guard = ZeroApiNetworkGuard(allow_sandboxed_children=True)

    with guard:
        completed = subprocess.run(
            ("/usr/bin/true",),
            check=False,
        )

    assert completed.returncode == 0
    assert guard.report()["child_process_policy"] == (
        "kernel_inherited_network_deny"
    )
    assert guard.process_creation_attempt_count == 0


def test_zero_api_guard_writes_measured_report_atomically(
    tmp_path,
) -> None:
    guard = ZeroApiNetworkGuard()
    output = tmp_path / "network.json"

    with guard:
        socket.getaddrinfo("127.0.0.1", 80)
    guard.write_report(output)

    assert json.loads(output.read_text(encoding="utf-8")) == {
        "schema_version": "guide-zero-api-network-report-v1",
        "guard_active": True,
        "passed": True,
        "process_guard_active": True,
        "kernel_network_sandbox_active": (
            network_guard_module._kernel_network_sandbox_active()
        ),
        "child_process_policy": "deny_process_creation",
        "provider_call_count": 0,
        "outbound_network_attempt_count": 0,
        "attempts": [],
        "process_creation_attempt_count": 0,
        "process_creation_attempts": [],
    }
    assert not tuple(tmp_path.glob(".*.tmp"))
    with pytest.raises(
        FileExistsError,
        match="network report already exists",
    ):
        guard.write_report(output)
