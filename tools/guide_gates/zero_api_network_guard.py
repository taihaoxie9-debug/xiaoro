from __future__ import annotations

from contextlib import AbstractContextManager
import ctypes
import ipaddress
import json
import multiprocessing.process
import os
from pathlib import Path
import socket
import subprocess
import sys
from threading import Lock
from typing import Any, Self

import httpx


NETWORK_REPORT_ENV = "XIAORO_ZERO_API_NETWORK_REPORT"
ZERO_API_SANDBOX_PROFILE = (
    "(version 1)"
    "(allow default)"
    "(deny network-outbound)"
    "(allow network-outbound (remote ip \"localhost:*\"))"
    "(allow network-inbound)"
)
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


class ZeroApiNetworkViolation(RuntimeError):
    pass


def _is_loopback_host(host: object) -> bool:
    if isinstance(host, bytes):
        try:
            host = host.decode("ascii")
        except UnicodeDecodeError:
            return False
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


def _address_host(address: object) -> object | None:
    if isinstance(address, tuple) and address:
        return address[0]
    return None


def _uses_real_http_transport(client: object) -> bool:
    transport = getattr(client, "_transport", None)
    return isinstance(
        transport,
        (httpx.HTTPTransport, httpx.AsyncHTTPTransport),
    )


def _kernel_network_sandbox_active() -> bool:
    if sys.platform != "darwin":
        return False
    try:
        sandbox = ctypes.CDLL(
            "/usr/lib/system/libsystem_sandbox.dylib"
        )
        sandbox_check = sandbox.sandbox_check
        sandbox_check.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
        ]
        sandbox_check.restype = ctypes.c_int
        return (
            sandbox_check(
                os.getpid(),
                b"network-outbound",
                0,
            )
            != 0
        )
    except (AttributeError, OSError):
        return False


class ZeroApiNetworkGuard(AbstractContextManager["ZeroApiNetworkGuard"]):
    def __init__(
        self,
        *,
        allow_sandboxed_children: bool = False,
    ) -> None:
        self._lock = Lock()
        self._allow_sandboxed_children = allow_sandboxed_children
        self._kernel_network_sandbox_active = False
        self._installed = False
        self._ever_installed = False
        self._attempts: list[dict[str, str]] = []
        self._process_creation_attempts: list[dict[str, str]] = []
        self._provider_call_count = 0
        self._outbound_network_attempt_count = 0
        self._originals: dict[str, Any] = {}

    @property
    def provider_call_count(self) -> int:
        with self._lock:
            return self._provider_call_count

    @property
    def outbound_network_attempt_count(self) -> int:
        with self._lock:
            return self._outbound_network_attempt_count

    @property
    def process_creation_attempt_count(self) -> int:
        with self._lock:
            return len(self._process_creation_attempts)

    @property
    def process_creation_attempts(self) -> list[dict[str, str]]:
        with self._lock:
            return [
                dict(item) for item in self._process_creation_attempts
            ]

    def __enter__(self) -> Self:
        self.install()
        return self

    def __exit__(self, *args: object) -> None:
        self.uninstall()

    def install(self) -> None:
        if self._installed:
            raise RuntimeError("zero API network guard is already installed")
        from app.guide.adapters.llm.provider_common import (
            OpenAIJsonClient,
        )

        self._kernel_network_sandbox_active = (
            _kernel_network_sandbox_active()
        )
        self._originals = {
            "socket.connect": socket.socket.connect,
            "socket.connect_ex": socket.socket.connect_ex,
            "socket.sendto": socket.socket.sendto,
            "socket.create_connection": socket.create_connection,
            "socket.getaddrinfo": socket.getaddrinfo,
            "socket.gethostbyname": socket.gethostbyname,
            "socket.gethostbyname_ex": socket.gethostbyname_ex,
            "httpx.Client.send": httpx.Client.send,
            "httpx.AsyncClient.send": httpx.AsyncClient.send,
            "OpenAIJsonClient.request": OpenAIJsonClient.request,
            "subprocess.Popen.__init__": subprocess.Popen.__init__,
            "multiprocessing.BaseProcess.start": (
                multiprocessing.process.BaseProcess.start
            ),
        }
        for name in _OS_PROCESS_FUNCTIONS:
            original = getattr(os, name, None)
            if callable(original):
                self._originals[f"os.{name}"] = original
        guard = self

        def guarded_connect(sock, address):
            host = _address_host(address)
            if host is None or _is_loopback_host(host):
                return guard._originals["socket.connect"](sock, address)
            guard._block_network("socket.connect", host)

        def guarded_connect_ex(sock, address):
            host = _address_host(address)
            if host is None or _is_loopback_host(host):
                return guard._originals["socket.connect_ex"](sock, address)
            guard._block_network("socket.connect_ex", host)

        def guarded_sendto(sock, data, *args):
            address = args[-1] if args else None
            host = _address_host(address)
            if host is None or _is_loopback_host(host):
                return guard._originals["socket.sendto"](sock, data, *args)
            guard._block_network("socket.sendto", host)

        def guarded_create_connection(address, *args, **kwargs):
            host = _address_host(address)
            if host is None or _is_loopback_host(host):
                return guard._originals["socket.create_connection"](
                    address,
                    *args,
                    **kwargs,
                )
            guard._block_network("socket.create_connection", host)

        def guarded_getaddrinfo(host, *args, **kwargs):
            if _is_loopback_host(host):
                return guard._originals["socket.getaddrinfo"](
                    host,
                    *args,
                    **kwargs,
                )
            guard._block_network("DNS", host)

        def guarded_gethostbyname(host):
            if _is_loopback_host(host):
                return guard._originals["socket.gethostbyname"](host)
            guard._block_network("DNS", host)

        def guarded_gethostbyname_ex(host):
            if _is_loopback_host(host):
                return guard._originals["socket.gethostbyname_ex"](host)
            guard._block_network("DNS", host)

        def guarded_httpx_send(client, request, *args, **kwargs):
            if (
                not _uses_real_http_transport(client)
                or _is_loopback_host(request.url.host)
            ):
                return guard._originals["httpx.Client.send"](
                    client,
                    request,
                    *args,
                    **kwargs,
                )
            guard._block_network("httpx", request.url.host)

        async def guarded_async_httpx_send(
            client,
            request,
            *args,
            **kwargs,
        ):
            if (
                not _uses_real_http_transport(client)
                or _is_loopback_host(request.url.host)
            ):
                return await guard._originals["httpx.AsyncClient.send"](
                    client,
                    request,
                    *args,
                    **kwargs,
                )
            guard._block_network("httpx", request.url.host)

        def guarded_provider_request(client, body, *, tool_name=None):
            transport = getattr(client, "_client", None)
            if (
                transport is not None
                and not _uses_real_http_transport(transport)
            ):
                return guard._originals["OpenAIJsonClient.request"](
                    client,
                    body,
                    tool_name=tool_name,
                )
            guard._block_provider(
                getattr(
                    getattr(client, "_client", None),
                    "base_url",
                    "provider",
                )
            )

        def guarded_popen_init(
            process: subprocess.Popen[Any],
            *args: object,
            **kwargs: object,
        ) -> None:
            if (
                guard._allow_sandboxed_children
                and guard._kernel_network_sandbox_active
            ):
                return guard._originals[
                    "subprocess.Popen.__init__"
                ](process, *args, **kwargs)
            process._child_created = False
            target = args[0] if args else kwargs.get("args")
            guard._block_process("subprocess.Popen", target)

        def guarded_process_start(
            process: multiprocessing.process.BaseProcess,
            *args: object,
            **kwargs: object,
        ) -> None:
            if (
                guard._allow_sandboxed_children
                and guard._kernel_network_sandbox_active
            ):
                return guard._originals[
                    "multiprocessing.BaseProcess.start"
                ](process, *args, **kwargs)
            guard._block_process(
                "multiprocessing.Process.start",
                getattr(process, "name", type(process).__name__),
            )

        socket.socket.connect = guarded_connect
        socket.socket.connect_ex = guarded_connect_ex
        socket.socket.sendto = guarded_sendto
        socket.create_connection = guarded_create_connection
        socket.getaddrinfo = guarded_getaddrinfo
        socket.gethostbyname = guarded_gethostbyname
        socket.gethostbyname_ex = guarded_gethostbyname_ex
        httpx.Client.send = guarded_httpx_send
        httpx.AsyncClient.send = guarded_async_httpx_send
        OpenAIJsonClient.request = guarded_provider_request
        subprocess.Popen.__init__ = guarded_popen_init
        multiprocessing.process.BaseProcess.start = guarded_process_start
        for name in _OS_PROCESS_FUNCTIONS:
            if f"os.{name}" not in self._originals:
                continue

            def blocked_os_call(
                *args: object,
                _name: str = name,
                **kwargs: object,
            ) -> Any:
                if (
                    guard._allow_sandboxed_children
                    and guard._kernel_network_sandbox_active
                ):
                    return guard._originals[f"os.{_name}"](
                        *args,
                        **kwargs,
                    )
                target = args[0] if args else kwargs
                guard._block_process(f"os.{_name}", target)

            setattr(os, name, blocked_os_call)
        self._installed = True
        self._ever_installed = True

    def uninstall(self) -> None:
        if not self._installed:
            return
        from app.guide.adapters.llm.provider_common import (
            OpenAIJsonClient,
        )

        socket.socket.connect = self._originals["socket.connect"]
        socket.socket.connect_ex = self._originals["socket.connect_ex"]
        socket.socket.sendto = self._originals["socket.sendto"]
        socket.create_connection = self._originals[
            "socket.create_connection"
        ]
        socket.getaddrinfo = self._originals["socket.getaddrinfo"]
        socket.gethostbyname = self._originals[
            "socket.gethostbyname"
        ]
        socket.gethostbyname_ex = self._originals[
            "socket.gethostbyname_ex"
        ]
        httpx.Client.send = self._originals["httpx.Client.send"]
        httpx.AsyncClient.send = self._originals[
            "httpx.AsyncClient.send"
        ]
        OpenAIJsonClient.request = self._originals[
            "OpenAIJsonClient.request"
        ]
        subprocess.Popen.__init__ = self._originals[
            "subprocess.Popen.__init__"
        ]
        multiprocessing.process.BaseProcess.start = self._originals[
            "multiprocessing.BaseProcess.start"
        ]
        for name in _OS_PROCESS_FUNCTIONS:
            original = self._originals.get(f"os.{name}")
            if original is not None:
                setattr(os, name, original)
        self._installed = False

    def _block_network(self, kind: str, target: object) -> None:
        normalized = str(target)
        with self._lock:
            self._outbound_network_attempt_count += 1
            self._attempts.append({
                "kind": kind,
                "target": normalized,
            })
        raise ZeroApiNetworkViolation(
            f"non-loopback {kind} is forbidden: {normalized}"
        )

    def _block_provider(self, target: object) -> None:
        normalized = str(target)
        with self._lock:
            self._provider_call_count += 1
            self._outbound_network_attempt_count += 1
            self._attempts.append({
                "kind": "provider",
                "target": normalized,
            })
        raise ZeroApiNetworkViolation(
            f"provider call is forbidden: {normalized}"
        )

    def _block_process(self, kind: str, target: object) -> None:
        rendered_target = repr(target)
        if len(rendered_target) > 500:
            rendered_target = f"{rendered_target[:497]}..."
        with self._lock:
            self._process_creation_attempts.append(
                {
                    "kind": kind,
                    "target": rendered_target,
                }
            )
        raise ZeroApiNetworkViolation(
            f"process creation is forbidden: {kind}"
        )

    def report(self) -> dict[str, object]:
        with self._lock:
            provider_calls = self._provider_call_count
            outbound_attempts = self._outbound_network_attempt_count
            attempts = [dict(item) for item in self._attempts]
            process_attempts = [
                dict(item) for item in self._process_creation_attempts
            ]
        return {
            "schema_version": "guide-zero-api-network-report-v1",
            "guard_active": self._ever_installed,
            "process_guard_active": self._ever_installed,
            "kernel_network_sandbox_active": (
                self._kernel_network_sandbox_active
            ),
            "child_process_policy": (
                "kernel_inherited_network_deny"
                if (
                    self._allow_sandboxed_children
                    and self._kernel_network_sandbox_active
                )
                else "deny_process_creation"
            ),
            "passed": (
                provider_calls == 0
                and outbound_attempts == 0
                and not process_attempts
            ),
            "provider_call_count": provider_calls,
            "outbound_network_attempt_count": outbound_attempts,
            "attempts": attempts,
            "process_creation_attempt_count": len(process_attempts),
            "process_creation_attempts": process_attempts,
        }

    def write_report(self, output_path: str | Path) -> None:
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        if output.exists() or output.is_symlink():
            raise FileExistsError(
                f"network report already exists: {output}"
            )
        temporary = output.parent / f".{output.name}.{os.getpid()}.tmp"
        payload = (
            json.dumps(
                self.report(),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        try:
            with os.fdopen(descriptor, "wb", closefd=True) as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.link(temporary, output)
            directory = os.open(output.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            temporary.unlink(missing_ok=True)


_PYTEST_GUARD: ZeroApiNetworkGuard | None = None


def pytest_configure(config) -> None:
    del config
    global _PYTEST_GUARD
    if _PYTEST_GUARD is not None:
        raise RuntimeError("zero API pytest guard installed twice")
    _PYTEST_GUARD = ZeroApiNetworkGuard(
        allow_sandboxed_children=True,
    )
    _PYTEST_GUARD.install()


def pytest_sessionfinish(session, exitstatus) -> None:
    del session, exitstatus
    guard = _PYTEST_GUARD
    if guard is None:
        return
    guard.uninstall()
    report_path = os.environ.get(NETWORK_REPORT_ENV)
    if report_path:
        guard.write_report(report_path)


def pytest_unconfigure(config) -> None:
    del config
    global _PYTEST_GUARD
    if _PYTEST_GUARD is not None:
        _PYTEST_GUARD.uninstall()
    _PYTEST_GUARD = None


__all__ = [
    "NETWORK_REPORT_ENV",
    "ZERO_API_SANDBOX_PROFILE",
    "ZeroApiNetworkGuard",
    "ZeroApiNetworkViolation",
]
