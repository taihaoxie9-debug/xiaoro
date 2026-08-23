from __future__ import annotations

import json
import socket

import httpx
import pytest

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
        "provider_call_count": 0,
        "outbound_network_attempt_count": 0,
        "attempts": [],
    }
    assert not tuple(tmp_path.glob(".*.tmp"))
    with pytest.raises(
        FileExistsError,
        match="network report already exists",
    ):
        guard.write_report(output)
