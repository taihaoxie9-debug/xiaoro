from __future__ import annotations

import argparse
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from hashlib import sha256
import hmac
import http.client
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import signal
import struct
import subprocess
import sys
import threading
import time
from types import MappingProxyType
from typing import Any, Callable, Sequence
from urllib.parse import urlsplit
import zlib

from app.guide.adapters.catalog import CanonicalProductReader
from app.guide.adapters.catalog.canonical_guide_catalog import (
    CanonicalGuideCatalog,
)
from app.guide.adapters.catalog.seed_product_assets import (
    load_seed_product_assets,
)
from app.guide.application.public_event_envelope import (
    project_frontend_product,
)
from app.guide.decision.recommendation import resolve_skin_match
from app.guide.intent.contracts import SkinConstraint
from app.guide.intent.responsibility_matrix import Responsibility
from app.guide.presentation.contracts import (
    CardDisplayContract,
    ProductCard,
)
from app.guide.presentation.copywriter_contracts import (
    CopywriterTelemetry,
    DirectFactComponent,
    PresentationSection,
    deterministic_copy_source,
    successful_copy_provenance,
)
from app.guide.presentation.public_contracts import (
    ComparisonCell,
    ComparisonRow,
    PublicPresentationContract,
    WinnerPresentation,
)
from app.guide.presentation.response_planning import build_product_card
from app.guide.retrieval.product_display_assets import (
    ProductDisplayBindingReader,
    load_product_display_assets,
)
from app.guide.understanding.image_contracts import (
    IdentityEvidenceConsistency,
    IdentityState,
    ImageIdentityObservation,
    ObservationState,
    OcrObservationState,
    VisualObservationState,
)
from app.guide.understanding.contracts import SkinTarget
from tools.guide_gates.attempt_ledger import (
    complete_attempt,
    consume_runtime_bound_attempt,
    read_attempt_context,
    read_ledger,
)
from tools.guide_gates.build_task11_readiness import (
    verify_task11_readiness,
)
from tools.guide_gates.run_bound_runtime import (
    RUNTIME_IDENTITY_FILENAME,
)
from tools.guide_gates.run_zero_api_runtime import (
    ZeroApiRuntimeError,
    verify_runtime_challenge,
    verify_runtime_identity,
)
from app.guide_runtime.composition import (
    GUIDE_PRODUCT_DISPLAY_MANIFEST_SHA256,
    GUIDE_PRODUCT_DISPLAY_RELATIVE_PATH,
    build_category_fact_reader,
    build_controlled_product_alias_registry,
)


class AuditBundleError(ValueError):
    pass


class BoundedAuditFailure(AuditBundleError):
    def __init__(
        self,
        *,
        turn_id: str,
        owner: str,
        failure_code: str,
        evidence_directory: str | Path,
        message: str | None = None,
    ) -> None:
        super().__init__(message or failure_code)
        self.turn_id = turn_id
        self.owner = owner
        self.failure_code = failure_code
        self.evidence_directory = Path(evidence_directory)


class BoundedContractError(AuditBundleError):
    def __init__(
        self,
        *,
        owner: str,
        failure_code: str,
        message: str | None = None,
    ) -> None:
        super().__init__(message or failure_code)
        self.owner = owner
        self.failure_code = failure_code


@dataclass(frozen=True, slots=True)
class _FixtureRuntimeProof:
    runtime_identity_bytes: bytes
    consumed_health_challenge: dict[str, str]


@dataclass(frozen=True, slots=True)
class _CanonicalPublicCatalog:
    catalog: CanonicalGuideCatalog
    product_ids: frozenset[int]
    variant_scopes_by_product: Mapping[
        int,
        frozenset[str | None],
    ]


ROOT = Path(__file__).resolve().parents[2]
_RUNTIME_CHALLENGE_PATH = "/__task11_runtime__/challenge"
_RUNTIME_SHUTDOWN_PATH = "/__task11_runtime__/shutdown"
_RUNTIME_CHALLENGE_SCHEMA = "guide-zero-api-runtime-challenge-v1"
_RUNTIME_IDENTITY_ARTIFACT = "runtime-identity.json"
_CONSUMED_CHALLENGE_ARTIFACT = (
    "consumed-runtime-health-challenge.json"
)
_FIXTURE_SANDBOX_ENV = "XIAORO_TASK11_FIXTURE_SANDBOX_SHA256"
_FIXTURE_SANDBOX_NONCE_ENV = "XIAORO_TASK11_FIXTURE_SANDBOX_NONCE"
_FIXTURE_SANDBOX_IDENTITY_PREFIX = "macos-sandbox-exec-loopback-only:"
FIXTURE_EVIDENCE_SCOPE = "frontend_fixture_only"
FIXTURE_BACKEND_PATH_CLAIM = False
_SEATBELT_READY_PREFIX = "XIAORO_SEATBELT_READY"
_SEATBELT_BEGIN_PREFIX = "XIAORO_SEATBELT_BEGIN"
_SEATBELT_END_PREFIX = "XIAORO_SEATBELT_END"
_SEATBELT_DRAIN_PREFIX = "XIAORO_SEATBELT_DRAIN"
_SEATBELT_CANARY_PREFIX = "XIAORO_SEATBELT_CANARY"
_SEATBELT_KERNEL_PATH = "/kernel"
_SEATBELT_EXTENSION_PATH = (
    "/System/Library/Extensions/Sandbox.kext/Contents/MacOS/Sandbox"
)
_SEATBELT_ROOT_CANARY_PORT = 9
_SEATBELT_CHILD_CANARY_PORT = 443
_SEATBELT_DRAIN_CANARY_PORT = 53
_CHROMIUM_IPV6_PROBE_TARGET = "[2001:4860:4860::8888]:443"
_NETWORK_TARGET_KEYS = frozenset({
    "address",
    "endpoint",
    "host",
    "hostname",
    "ip_endpoint",
    "original_url",
    "proxy_server",
    "remote_address",
    "url",
})
_BROWSER_RESOURCE_TYPES = frozenset({
    "document",
    "eventsource",
    "fetch",
    "font",
    "image",
    "manifest",
    "media",
    "other",
    "script",
    "stylesheet",
    "texttrack",
    "websocket",
    "xhr",
})
_MAX_SCREENSHOT_FILE_BYTES = 64 * 1024 * 1024
_MAX_SCREENSHOT_WIDTH = 8192
_MAX_SCREENSHOT_HEIGHT = 32768
_MAX_SCREENSHOT_PIXELS = 50_000_000


def _canonical_bytes(payload: object) -> bytes:
    return (
        json.dumps(
            payload,
            ensure_ascii=True,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _fixture_sandbox_profile(measurement_nonce: str) -> str:
    if re.fullmatch(r"[0-9a-f]{64}", measurement_nonce) is None:
        raise AuditBundleError("fixture sandbox nonce is invalid")
    return (
        "(version 1)"
        "(allow default)"
        "(deny network-outbound "
        "(with telemetry) "
        f"(with message \"{measurement_nonce}\"))"
        "(allow network-outbound (remote ip \"localhost:*\"))"
        "(allow network-inbound)"
    )


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


def _fixture_runtime_request(
    *,
    base_url: str,
    method: str,
    path: str,
    payload: dict[str, object] | None,
) -> dict[str, object]:
    parsed = urlsplit(base_url)
    if (
        parsed.scheme != "http"
        or not _is_loopback_host(parsed.hostname)
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise AuditBundleError(
            "fixture runtime base URL must be loopback HTTP"
        )
    try:
        port = parsed.port
    except ValueError as exc:
        raise AuditBundleError(
            "fixture runtime base URL is invalid"
        ) from exc
    if port is None:
        raise AuditBundleError(
            "fixture runtime base URL requires an explicit port"
        )
    body = (
        None
        if payload is None
        else json.dumps(
            payload,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    )
    connection = http.client.HTTPConnection(
        parsed.hostname,
        port,
        timeout=10,
    )
    try:
        connection.request(
            method,
            path,
            body=body,
            headers=(
                {}
                if body is None
                else {"Content-Type": "application/json"}
            ),
        )
        response = connection.getresponse()
        content = response.read()
    except OSError as exc:
        raise AuditBundleError(
            "fixture runtime challenge request failed"
        ) from exc
    finally:
        connection.close()
    try:
        decoded = json.loads(content)
    except json.JSONDecodeError as exc:
        raise AuditBundleError(
            "fixture runtime challenge response is invalid"
        ) from exc
    if response.status != 200:
        message = (
            decoded.get("error")
            if isinstance(decoded, dict)
            else None
        )
        raise AuditBundleError(
            str(message or "fixture runtime challenge was rejected")
        )
    if not isinstance(decoded, dict):
        raise AuditBundleError(
            "fixture runtime challenge response is invalid"
        )
    return decoded


def _consume_runtime_health_challenge(
    *,
    base_url: str,
    runtime_identity_sha256: str,
    runtime_public_key: str,
    request_json: Callable[
        [str, str, dict[str, object] | None],
        dict[str, object],
    ] | None = None,
) -> dict[str, str]:
    requester = request_json or (
        lambda method, path, payload: _fixture_runtime_request(
            base_url=base_url,
            method=method,
            path=path,
            payload=payload,
        )
    )
    issued = requester("GET", _RUNTIME_CHALLENGE_PATH, None)
    try:
        verified_issued = verify_runtime_challenge(
            challenge=issued,
            runtime_identity_sha256=runtime_identity_sha256,
            runtime_public_key=runtime_public_key,
        )
    except ZeroApiRuntimeError as exc:
        raise AuditBundleError(
            "fixture runtime health challenge is invalid"
        ) from exc
    challenge = verified_issued["challenge"]
    consumed = requester(
        "POST",
        _RUNTIME_CHALLENGE_PATH,
        {"challenge": challenge},
    )
    try:
        verified_consumed = verify_runtime_challenge(
            challenge=consumed,
            runtime_identity_sha256=runtime_identity_sha256,
            runtime_public_key=runtime_public_key,
        )
    except ZeroApiRuntimeError as exc:
        raise AuditBundleError(
            "fixture runtime health challenge is invalid"
        ) from exc
    if verified_consumed != verified_issued:
        raise AuditBundleError(
            "fixture runtime health challenge consumption mismatch"
        )
    return {
        str(key): str(value)
        for key, value in verified_consumed.items()
    }


def _verified_fixture_runtime(
    *,
    base_url: str,
    runtime_identity_path: Path,
    expected_manifest_sha256: str,
) -> _FixtureRuntimeProof:
    identity_bytes = runtime_identity_path.read_bytes()
    identity = _read_object(runtime_identity_path)
    manifest_path = identity.get("candidate_manifest_path")
    process_identity = identity.get("process_identity")
    parsed = urlsplit(base_url)
    try:
        port = parsed.port
    except ValueError as exc:
        raise AuditBundleError(
            "fixture runtime base URL is invalid"
        ) from exc
    if (
        not isinstance(manifest_path, str)
        or not isinstance(process_identity, dict)
        or isinstance(process_identity.get("pid"), bool)
        or not isinstance(process_identity.get("pid"), int)
        or parsed.scheme != "http"
        or not _is_loopback_host(parsed.hostname)
        or port is None
    ):
        raise AuditBundleError("fixture runtime identity is invalid")
    pid = int(process_identity["pid"])
    try:
        verified = verify_runtime_identity(
            identity_path=runtime_identity_path,
            manifest_path=manifest_path,
            expected_manifest_sha256=expected_manifest_sha256,
            expected_host=str(parsed.hostname),
            expected_port=port,
            expected_pid=pid,
        )
        os.kill(pid, 0)
    except (OSError, ZeroApiRuntimeError) as exc:
        raise AuditBundleError(
            "fixture runtime identity is invalid"
        ) from exc
    if verified != identity:
        raise AuditBundleError("fixture runtime identity is invalid")
    if identity_bytes != _canonical_bytes(identity):
        raise AuditBundleError("fixture runtime identity is invalid")
    runtime_identity_sha256 = sha256(identity_bytes).hexdigest()
    consumed = _consume_runtime_health_challenge(
        base_url=base_url,
        runtime_identity_sha256=runtime_identity_sha256,
        runtime_public_key=str(identity["runtime_public_key"]),
    )
    return _FixtureRuntimeProof(
        runtime_identity_bytes=identity_bytes,
        consumed_health_challenge=consumed,
    )


def _persist_fixture_runtime_proof(
    *,
    output: Path,
    proof: _FixtureRuntimeProof,
) -> dict[str, str]:
    challenge = proof.consumed_health_challenge
    runtime_identity_sha256 = sha256(
        proof.runtime_identity_bytes
    ).hexdigest()
    try:
        identity = json.loads(proof.runtime_identity_bytes)
        verified_challenge = verify_runtime_challenge(
            challenge=challenge,
            runtime_identity_sha256=runtime_identity_sha256,
            runtime_public_key=str(identity["runtime_public_key"]),
        )
    except (
        json.JSONDecodeError,
        KeyError,
        TypeError,
        ZeroApiRuntimeError,
    ) as exc:
        raise AuditBundleError(
            "fixture runtime provenance is invalid"
        ) from exc
    challenge_sha256 = verified_challenge["challenge_sha256"]
    _write_bytes_exclusive(
        output / _RUNTIME_IDENTITY_ARTIFACT,
        proof.runtime_identity_bytes,
        label="fixture runtime identity",
    )
    _write_json_exclusive(
        output / _CONSUMED_CHALLENGE_ARTIFACT,
        challenge,
        label="fixture consumed runtime health challenge",
    )
    return {
        "runtime_identity_sha256": runtime_identity_sha256,
        "consumed_health_challenge_sha256": challenge_sha256,
    }


def shutdown_zero_api_runtime(
    *,
    base_url: str,
    runtime_identity_path: str | Path,
    expected_manifest_sha256: str,
) -> None:
    identity_path = Path(runtime_identity_path)
    identity = _read_object(identity_path)
    manifest_path = identity.get("candidate_manifest_path")
    process_identity = identity.get("process_identity")
    parsed = urlsplit(base_url)
    try:
        port = parsed.port
    except ValueError as exc:
        raise AuditBundleError(
            "fixture runtime base URL is invalid"
        ) from exc
    if (
        not isinstance(manifest_path, str)
        or not isinstance(process_identity, dict)
        or type(process_identity.get("pid")) is not int
        or not isinstance(identity.get("runtime_nonce"), str)
        or parsed.scheme != "http"
        or not _is_loopback_host(parsed.hostname)
        or port is None
    ):
        raise AuditBundleError("fixture runtime identity is invalid")
    try:
        verify_runtime_identity(
            identity_path=identity_path,
            manifest_path=manifest_path,
            expected_manifest_sha256=expected_manifest_sha256,
            expected_host=str(parsed.hostname),
            expected_port=port,
            expected_pid=int(process_identity["pid"]),
        )
    except (ZeroApiRuntimeError, OSError) as exc:
        raise AuditBundleError(
            "fixture runtime identity is invalid"
        ) from exc
    response = _fixture_runtime_request(
        base_url=base_url,
        method="POST",
        path=_RUNTIME_SHUTDOWN_PATH,
        payload={"runtime_nonce": identity["runtime_nonce"]},
    )
    if response != {"status": "stopping"}:
        raise AuditBundleError(
            "fixture runtime shutdown was not acknowledged"
        )


def _network_target_host(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    parsed = urlsplit(text)
    if parsed.scheme in {"http", "https", "ws", "wss"}:
        return parsed.hostname
    if parsed.scheme in {"about", "blob", "data", "file"}:
        return None
    bracketed = re.fullmatch(r"\[([0-9a-fA-F:]+)\](?::\d+)?", text)
    if bracketed is not None:
        return bracketed.group(1)
    host_port = re.fullmatch(r"([^:/\\s]+):\d+", text)
    if host_port is not None:
        return host_port.group(1)
    try:
        ipaddress.ip_address(text)
    except ValueError:
        if "." in text and "/" not in text and " " not in text:
            return text
        return None
    return text


def _validate_fixture_network_evidence(
    *,
    base_url: str,
    browser_requests: list[dict[str, str]],
    process_tree_attempts: list[dict[str, object]],
) -> dict[str, int]:
    parsed = urlsplit(base_url)
    if not _is_loopback_host(parsed.hostname):
        raise AuditBundleError(
            "fixture runtime base URL must be loopback"
        )
    browser_non_loopback = [
        request
        for request in browser_requests
        if (
            (host := _network_target_host(request.get("url")))
            is not None
            and not _is_loopback_host(host)
        )
    ]
    if browser_non_loopback or process_tree_attempts:
        raise AuditBundleError(
            "fixture browser observed a non-loopback request"
        )
    return {
        "browser_request_count": len(browser_requests),
        "browser_observed_non_loopback_attempt_count": 0,
        "process_tree_non_loopback_attempt_count": 0,
    }


def _netlog_non_loopback_attempts(
    path: Path,
) -> list[dict[str, object]]:
    events = _load_chromium_netlog_events(path)
    attempts: list[dict[str, object]] = []

    def inspect(
        value: object,
        *,
        event_index: int,
        event_type: object,
        key: str | None = None,
    ) -> None:
        if isinstance(value, dict):
            for child_key, child in value.items():
                inspect(
                    child,
                    event_index=event_index,
                    event_type=event_type,
                    key=str(child_key),
                )
            return
        if isinstance(value, list):
            for child in value:
                inspect(
                    child,
                    event_index=event_index,
                    event_type=event_type,
                    key=key,
                )
            return
        if key not in _NETWORK_TARGET_KEYS:
            return
        host = _network_target_host(value)
        if host is None or _is_loopback_host(host):
            return
        attempts.append({
            "event_index": event_index,
            "event_type": event_type,
            "field": key,
            "target": value,
        })

    for index, event in enumerate(events):
        inspect(
            event.get("params", {}),
            event_index=index,
            event_type=event.get("type"),
        )
    unique = {
        json.dumps(item, ensure_ascii=True, sort_keys=True): item
        for item in attempts
    }
    return [unique[key] for key in sorted(unique)]


def _load_chromium_netlog_events(
    path: Path,
) -> list[dict[str, object]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        events = payload["events"]
    except (OSError, KeyError, json.JSONDecodeError, TypeError) as exc:
        raise AuditBundleError(
            "Chromium network log is invalid"
        ) from exc
    if not isinstance(events, list):
        raise AuditBundleError("Chromium network log is invalid")
    if any(not isinstance(event, dict) for event in events):
        raise AuditBundleError("Chromium network log is invalid")
    return events


def _netlog_observed_urls(path: Path) -> frozenset[str]:
    events = _load_chromium_netlog_events(path)
    urls: set[str] = set()

    def visit(value: object, *, key: str | None = None) -> None:
        if isinstance(value, dict):
            for child_key, child in value.items():
                visit(child, key=str(child_key))
            return
        if isinstance(value, list):
            for child in value:
                visit(child, key=key)
            return
        if key not in {"url", "original_url"} or not isinstance(value, str):
            return
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https", "ws", "wss"}:
            return
        urls.add(parsed._replace(fragment="").geturl())

    for event in events:
        visit(event.get("params", {}))
    return frozenset(urls)


def _validate_fixture_request_bindings(
    *,
    browser_requests: list[dict[str, str]],
    netlog_urls: frozenset[str],
) -> None:
    bound_urls: set[str] = set()
    for request in browser_requests:
        resource_type = request.get("resource_type")
        if resource_type not in _BROWSER_RESOURCE_TYPES:
            raise AuditBundleError(
                "fixture browser request resource type is invalid"
            )
        url = request.get("url")
        method = request.get("method")
        if not isinstance(url, str) or not isinstance(method, str):
            raise AuditBundleError(
                "fixture browser request evidence is invalid"
            )
        parsed = urlsplit(url)
        stream_post = (
            method.upper() == "POST"
            and parsed.path == "/api/v1/chat/stream"
        )
        if resource_type != "document" or stream_post:
            bound_urls.add(
                parsed._replace(fragment="").geturl()
            )
    if not netlog_urls:
        raise AuditBundleError(
            "Chromium network log is empty for browser requests"
        )
    missing = sorted(bound_urls - netlog_urls)
    if missing:
        raise AuditBundleError(
            "Chromium network log does not bind browser requests: "
            + ", ".join(missing)
        )


def _validate_screenshot_png(
    path: Path,
    *,
    request: Mapping[str, object],
) -> None:
    try:
        with path.open("rb") as stream:
            raw = stream.read(_MAX_SCREENSHOT_FILE_BYTES + 1)
    except OSError as exc:
        raise AuditBundleError("screenshot PNG is unreadable") from exc
    if len(raw) > _MAX_SCREENSHOT_FILE_BYTES:
        raise AuditBundleError("screenshot PNG is too large")
    if not raw.startswith(b"\x89PNG\r\n\x1a\n"):
        raise AuditBundleError("screenshot PNG signature is invalid")
    offset = 8
    width: int | None = None
    height: int | None = None
    bit_depth: int | None = None
    color_type: int | None = None
    compression: int | None = None
    filter_method: int | None = None
    interlace: int | None = None
    compressed = bytearray()
    saw_idat = False
    saw_iend = False
    while offset < len(raw):
        if offset + 12 > len(raw):
            raise AuditBundleError("screenshot PNG chunk is truncated")
        length = struct.unpack(">I", raw[offset : offset + 4])[0]
        kind = raw[offset + 4 : offset + 8]
        end = offset + 12 + length
        if end > len(raw):
            raise AuditBundleError("screenshot PNG chunk is truncated")
        data = raw[offset + 8 : offset + 8 + length]
        checksum = struct.unpack(
            ">I",
            raw[offset + 8 + length : end],
        )[0]
        if checksum != (zlib.crc32(kind + data) & 0xFFFFFFFF):
            raise AuditBundleError("screenshot PNG checksum is invalid")
        if kind == b"IHDR":
            if width is not None or length != 13 or offset != 8:
                raise AuditBundleError("screenshot PNG header is invalid")
            (
                width,
                height,
                bit_depth,
                color_type,
                compression,
                filter_method,
                interlace,
            ) = struct.unpack(">IIBBBBB", data)
        elif kind == b"IDAT":
            if width is None:
                raise AuditBundleError("screenshot PNG IDAT order is invalid")
            saw_idat = saw_idat or bool(data)
            compressed.extend(data)
        elif kind == b"IEND":
            if length != 0 or width is None or saw_iend:
                raise AuditBundleError("screenshot PNG end chunk is invalid")
            saw_iend = True
            offset = end
            break
        offset = end
    if not saw_iend or offset != len(raw) or not saw_idat:
        raise AuditBundleError("screenshot PNG structure is incomplete")
    if (
        width is None
        or height is None
        or bit_depth != 8
        or color_type != 2
        or compression != 0
        or filter_method != 0
        or interlace != 0
        or width <= 0
        or height <= 0
        or width > _MAX_SCREENSHOT_WIDTH
        or height > _MAX_SCREENSHOT_HEIGHT
        or width * height > _MAX_SCREENSHOT_PIXELS
    ):
        raise AuditBundleError("screenshot PNG dimensions or structure are invalid")
    viewport = request.get("viewport")
    if viewport is not None:
        if not isinstance(viewport, dict):
            raise AuditBundleError("screenshot viewport is invalid")
        expected_width = viewport.get("width")
        expected_height = viewport.get("height")
        if (
            type(expected_width) is not int
            or type(expected_height) is not int
            or width != expected_width
            or height < expected_height
        ):
            raise AuditBundleError(
                "screenshot PNG dimensions or structure are invalid"
            )
    encoded_row_bytes = 1 + width * 3
    previous = bytes(width * 3)
    pending = bytearray()
    remaining = bytes(compressed)
    color_counts = [0] * 4096
    channel_minimums = [255, 255, 255]
    channel_maximums = [0, 0, 0]
    inflater = zlib.decompressobj()

    def paeth(left: int, above: int, upper_left: int) -> int:
        estimate = left + above - upper_left
        left_distance = abs(estimate - left)
        above_distance = abs(estimate - above)
        upper_left_distance = abs(estimate - upper_left)
        if (
            left_distance <= above_distance
            and left_distance <= upper_left_distance
        ):
            return left
        if above_distance <= upper_left_distance:
            return above
        return upper_left

    try:
        for _ in range(height):
            while len(pending) < encoded_row_bytes:
                compressed_before = len(remaining)
                produced = inflater.decompress(
                    remaining,
                    encoded_row_bytes - len(pending),
                )
                pending.extend(produced)
                remaining = inflater.unconsumed_tail
                if (
                    not produced
                    and len(remaining) == compressed_before
                ):
                    raise AuditBundleError(
                        "screenshot PNG scanlines are invalid"
                    )
                if len(pending) < encoded_row_bytes and not remaining:
                    raise AuditBundleError(
                        "screenshot PNG scanlines are invalid"
                    )
            filter_type = pending[0]
            if filter_type > 4:
                raise AuditBundleError(
                    "screenshot PNG scanlines are invalid"
                )
            current = bytearray(pending[1:])
            pending.clear()
            for index, encoded in enumerate(current):
                left = current[index - 3] if index >= 3 else 0
                above = previous[index]
                upper_left = previous[index - 3] if index >= 3 else 0
                predictor = (
                    0
                    if filter_type == 0
                    else left
                    if filter_type == 1
                    else above
                    if filter_type == 2
                    else (left + above) // 2
                    if filter_type == 3
                    else paeth(left, above, upper_left)
                )
                current[index] = (encoded + predictor) & 0xFF
            for index in range(0, len(current), 3):
                red, green, blue = current[index : index + 3]
                color_counts[
                    ((red >> 4) << 8)
                    | ((green >> 4) << 4)
                    | (blue >> 4)
                ] += 1
                for channel, value in enumerate((red, green, blue)):
                    channel_minimums[channel] = min(
                        channel_minimums[channel],
                        value,
                    )
                    channel_maximums[channel] = max(
                        channel_maximums[channel],
                        value,
                    )
            previous = bytes(current)
        extra = inflater.decompress(remaining, 1)
    except zlib.error as exc:
        raise AuditBundleError(
            "screenshot PNG image data is invalid"
        ) from exc
    if (
        pending
        or extra
        or inflater.unconsumed_tail
        or inflater.unused_data
        or not inflater.eof
    ):
        raise AuditBundleError("screenshot PNG scanlines are invalid")

    pixel_count = width * height
    dominant_count = max(color_counts)
    distinct_bins = sum(count > 0 for count in color_counts)
    maximum_span = max(
        maximum - minimum
        for minimum, maximum in zip(
            channel_minimums,
            channel_maximums,
            strict=True,
        )
    )
    minimum_non_dominant = max(8, (pixel_count + 199) // 200)
    if (
        distinct_bins < 2
        or maximum_span < 16
        or pixel_count - dominant_count < minimum_non_dominant
    ):
        raise AuditBundleError(
            "screenshot PNG has insufficient visual content"
        )


def _build_fixture_sandbox_audit(
    *,
    base_url: str,
    browser_requests: list[dict[str, str]],
    netlog_path: Path,
    sandbox_profile: str,
    measurement_nonce: str,
    seatbelt_raw: bytes,
    logger_stderr: bytes,
    logger_returncode: int,
    sandbox_process_group_id: int,
    process_group_quiescent: bool,
) -> dict[str, object]:
    expected_profile = _fixture_sandbox_profile(measurement_nonce)
    if not hmac.compare_digest(sandbox_profile, expected_profile):
        raise AuditBundleError("fixture sandbox identity is invalid")
    if logger_returncode not in {0, 130, -2}:
        raise AuditBundleError("fixture Seatbelt logger exited unexpectedly")
    try:
        stderr_text = logger_stderr.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise AuditBundleError(
            "fixture Seatbelt logger stderr is invalid"
        ) from exc
    unexpected_stderr = tuple(
        line
        for line in stderr_text.splitlines()
        if line
        and not line.startswith("Filtering the log data using ")
    )
    if unexpected_stderr:
        raise AuditBundleError("fixture Seatbelt logger reported an error")
    try:
        raw_text = seatbelt_raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise AuditBundleError(
            "fixture Seatbelt log is not UTF-8 NDJSON"
        ) from exc
    events: list[dict[str, object]] = []
    for line_number, line in enumerate(raw_text.splitlines(), start=1):
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise AuditBundleError(
                "fixture Seatbelt log contains malformed NDJSON"
            ) from exc
        if not isinstance(event, dict):
            raise AuditBundleError(
                "fixture Seatbelt log event must be an object"
            )
        event["_line_number"] = line_number
        events.append(event)
    loss_events = [
        event for event in events
        if event.get("eventType") == "lossEvent"
    ]
    if loss_events:
        raise AuditBundleError("fixture Seatbelt logger lost events")

    ready_marker = f"{_SEATBELT_READY_PREFIX}:{measurement_nonce}"
    ready_indexes = [
        index
        for index, event in enumerate(events)
        if (
            event.get("processImagePath") == "/usr/bin/logger"
            and event.get("eventMessage") == ready_marker
        )
    ]
    if not ready_indexes:
        raise AuditBundleError(
            "fixture Seatbelt readiness marker is invalid"
        )
    begin_pattern = re.compile(
        rf"^{_SEATBELT_BEGIN_PREFIX}:{measurement_nonce}:(\d+)$"
    )
    end_pattern = re.compile(
        rf"^{_SEATBELT_END_PREFIX}:{measurement_nonce}:(\d+)$"
    )
    drain_marker = f"{_SEATBELT_DRAIN_PREFIX}:{measurement_nonce}"
    root_child_pattern = re.compile(
        rf"^{_SEATBELT_CANARY_PREFIX}:{measurement_nonce}:"
        rf"root_child:(\d+):{_SEATBELT_ROOT_CANARY_PORT}$"
    )
    descendant_pattern = re.compile(
        rf"^{_SEATBELT_CANARY_PREFIX}:{measurement_nonce}:"
        rf"descendant:(\d+):{_SEATBELT_CHILD_CANARY_PORT}$"
    )
    drain_pattern = re.compile(
        rf"^{_SEATBELT_CANARY_PREFIX}:{measurement_nonce}:"
        rf"drain:(\d+):{_SEATBELT_DRAIN_CANARY_PORT}$"
    )

    def markers(
        pattern: re.Pattern[str],
    ) -> list[tuple[int, re.Match[str]]]:
        output: list[tuple[int, re.Match[str]]] = []
        for index, event in enumerate(events):
            if event.get("processImagePath") != "/usr/bin/logger":
                continue
            message = event.get("eventMessage")
            if not isinstance(message, str):
                continue
            match = pattern.fullmatch(message)
            if match is not None:
                output.append((index, match))
        return output

    begin = markers(begin_pattern)
    end = markers(end_pattern)
    root_child = markers(root_child_pattern)
    descendant = markers(descendant_pattern)
    drain = markers(drain_pattern)
    drain_indexes = [
        index
        for index, event in enumerate(events)
        if (
            event.get("processImagePath") == "/usr/bin/logger"
            and event.get("eventMessage") == drain_marker
        )
    ]
    if len(begin) != 1 or len(end) != 1 or len(drain_indexes) != 1:
        raise AuditBundleError(
            "fixture Seatbelt begin/end/drain markers are invalid"
        )
    if (
        len(root_child) != 1
        or len(descendant) != 1
        or len(drain) != 1
    ):
        raise AuditBundleError(
            "fixture Seatbelt child canary marker is invalid"
        )
    root_pid = int(begin[0][1].group(1))
    end_pid = int(end[0][1].group(1))
    root_child_pid = int(root_child[0][1].group(1))
    descendant_pid = int(descendant[0][1].group(1))
    drain_pid = int(drain[0][1].group(1))
    if (
        root_pid != end_pid
        or sandbox_process_group_id != root_pid
        or process_group_quiescent is not True
        or root_child_pid in {root_pid, descendant_pid}
        or descendant_pid == root_pid
        or not (
            ready_indexes[0]
            < begin[0][0]
            < root_child[0][0]
            < descendant[0][0]
            < drain[0][0]
            < end[0][0]
            < drain_indexes[0]
        )
    ):
        raise AuditBundleError(
            "fixture Seatbelt marker order or identity is invalid"
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
    for event in events:
        if (
            event.get("processImagePath") != _SEATBELT_KERNEL_PATH
            or event.get("senderImagePath")
            != _SEATBELT_EXTENSION_PATH
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
                duplicate_denials.append({
                    "count": int(duplicate_match.group("count")),
                    "process": duplicate_match.group("process"),
                    "pid": int(duplicate_match.group("pid")),
                    "port": int(duplicate_match.group("port")),
                    "line_number": event["_line_number"],
                })
                continue
            if measurement_nonce in message:
                raise AuditBundleError(
                    "fixture Seatbelt denial event is malformed"
                )
            continue
        denials.append({
            "process": match.group("process"),
            "pid": int(match.group("pid")),
            "port": int(match.group("port")),
            "line_number": event["_line_number"],
        })
    root_canaries = [
        item for item in denials
        if (
            item["pid"] == root_child_pid
            and item["port"] == _SEATBELT_ROOT_CANARY_PORT
        )
    ]
    if len(root_canaries) != 1:
        raise AuditBundleError(
            "fixture Seatbelt root canary denial is missing"
        )
    child_canaries = [
        item for item in denials
        if (
            item["pid"] == descendant_pid
            and item["port"] == _SEATBELT_CHILD_CANARY_PORT
        )
    ]
    if len(child_canaries) != 1:
        raise AuditBundleError(
            "fixture Seatbelt child canary denial is missing"
        )
    drain_canaries = [
        item for item in denials
        if (
            item["pid"] == drain_pid
            and item["port"] == _SEATBELT_DRAIN_CANARY_PORT
        )
    ]
    if len(drain_canaries) != 1:
        raise AuditBundleError(
            "fixture Seatbelt drain canary denial is missing"
        )
    root_denial_index = int(root_canaries[0]["line_number"]) - 1
    descendant_denial_index = int(
        child_canaries[0]["line_number"]
    ) - 1
    drain_denial_index = int(drain_canaries[0]["line_number"]) - 1
    if not (
        begin[0][0]
        < root_denial_index
        < descendant_denial_index
        < root_child[0][0]
        < descendant[0][0]
        and drain[0][0]
        < drain_denial_index
        < end[0][0]
        < drain_indexes[0]
    ):
        raise AuditBundleError(
            "fixture Seatbelt canary delivery order is invalid"
        )
    canary_lines = {
        root_canaries[0]["line_number"],
        child_canaries[0]["line_number"],
        drain_canaries[0]["line_number"],
    }
    netlog_urls = _netlog_observed_urls(netlog_path)
    _validate_fixture_request_bindings(
        browser_requests=browser_requests,
        netlog_urls=netlog_urls,
    )
    netlog_attempts = _netlog_non_loopback_attempts(netlog_path)
    probe_denials = [
        item
        for item in denials
        if (
            item["process"] == "chrome-headless-shell"
            and item["port"] == _SEATBELT_CHILD_CANARY_PORT
            and item["line_number"] not in canary_lines
        )
    ]
    probe_duplicate_denials = [
        item
        for item in duplicate_denials
        if (
            item["process"] == "chrome-headless-shell"
            and item["port"] == _SEATBELT_CHILD_CANARY_PORT
        )
    ]
    environmental_probe_attempts = (
        bool(netlog_attempts)
        and bool(probe_denials or probe_duplicate_denials)
        and all(
            item["target"] == _CHROMIUM_IPV6_PROBE_TARGET
            and item["event_type"] in {46, 94}
            for item in netlog_attempts
        )
    )
    if environmental_probe_attempts and not all(
        begin[0][0]
        < int(item["line_number"]) - 1
        < end[0][0]
        for item in (*probe_denials, *probe_duplicate_denials)
    ):
        raise AuditBundleError(
            "fixture Chromium probe denial order is invalid"
        )
    allowed_duplicate_keys = {
        (root_child_pid, _SEATBELT_ROOT_CANARY_PORT),
        (descendant_pid, _SEATBELT_CHILD_CANARY_PORT),
        (drain_pid, _SEATBELT_DRAIN_CANARY_PORT),
    }
    if environmental_probe_attempts:
        allowed_duplicate_keys.update(
            (int(item["pid"]), int(item["port"]))
            for item in probe_denials
        )
        allowed_duplicate_keys.update(
            (int(item["pid"]), int(item["port"]))
            for item in probe_duplicate_denials
        )
    if any(
        (int(item["pid"]), int(item["port"]))
        not in allowed_duplicate_keys
        for item in duplicate_denials
    ):
        raise AuditBundleError(
            "fixture Seatbelt denial event is malformed"
        )
    process_tree_attempts = [
        item
        for item in denials
        if (
            item["line_number"] not in canary_lines
            and not (
                environmental_probe_attempts
                and item in probe_denials
            )
        )
    ]
    if not environmental_probe_attempts:
        process_tree_attempts.extend(
            {
                "source": "chromium_netlog",
                **item,
            }
            for item in netlog_attempts
        )
    counts = _validate_fixture_network_evidence(
        base_url=base_url,
        browser_requests=browser_requests,
        process_tree_attempts=process_tree_attempts,
    )
    sandbox_profile_sha256 = sha256(
        sandbox_profile.encode("utf-8")
    ).hexdigest()
    return {
        "schema_version": "guide-fixture-browser-sandbox-audit-v2",
        "passed": True,
        "evidence_scope": FIXTURE_EVIDENCE_SCOPE,
        "backend_path_claim": FIXTURE_BACKEND_PATH_CLAIM,
        "sandbox_identity": (
            _FIXTURE_SANDBOX_IDENTITY_PREFIX
            + sandbox_profile_sha256
        ),
        "sandbox_profile_sha256": sandbox_profile_sha256,
        "netlog_sha256": sha256(netlog_path.read_bytes()).hexdigest(),
        "enforcement": "macos-sandbox-exec-loopback-only",
        "measurement": "macos-unified-log-seatbelt-kernel",
        "measurement_nonce": measurement_nonce,
        "seatbelt_raw_ndjson_sha256": sha256(
            seatbelt_raw
        ).hexdigest(),
        "seatbelt_raw_byte_count": len(seatbelt_raw),
        "seatbelt_event_count": len(events),
        "seatbelt_canary_denial_count": 3,
        "logger_ready": True,
        "logger_readiness_marker_count": len(ready_indexes),
        "logger_loss_event_count": len(loss_events),
        "logger_returncode": logger_returncode,
        "root_pid": root_pid,
        "sandbox_process_group_id": sandbox_process_group_id,
        "process_group_quiescent": process_group_quiescent,
        "root_child_canary_pid": root_child_pid,
        "descendant_canary_pid": descendant_pid,
        "drain_canary_pid": drain_pid,
        "canary_denials": [
            root_canaries[0],
            child_canaries[0],
            drain_canaries[0],
        ],
        "blocked_environmental_probe_count": (
            len(netlog_attempts)
            if environmental_probe_attempts
            else 0
        ),
        "blocked_environmental_probe_duplicate_count": (
            len(probe_duplicate_denials)
            if environmental_probe_attempts
            else 0
        ),
        "blocked_environmental_probe_targets": (
            sorted({
                str(item["target"])
                for item in netlog_attempts
            })
            if environmental_probe_attempts
            else []
        ),
        "attempts": process_tree_attempts,
        **counts,
    }


def _fixture_sandbox_context() -> dict[str, str] | None:
    measurement_nonce = os.environ.get(_FIXTURE_SANDBOX_NONCE_ENV)
    marker = os.environ.get(_FIXTURE_SANDBOX_ENV)
    if (
        not isinstance(measurement_nonce, str)
        or re.fullmatch(r"[0-9a-f]{64}", measurement_nonce) is None
        or not isinstance(marker, str)
    ):
        return None
    sandbox_profile = _fixture_sandbox_profile(measurement_nonce)
    sandbox_profile_sha256 = sha256(
        sandbox_profile.encode("utf-8")
    ).hexdigest()
    if not hmac.compare_digest(marker, sandbox_profile_sha256):
        return None
    return {
        "measurement_nonce": measurement_nonce,
        "sandbox_profile": sandbox_profile,
        "sandbox_profile_sha256": sandbox_profile_sha256,
    }


def _fixture_sandbox_active() -> bool:
    return _fixture_sandbox_context() is not None


def _emit_seatbelt_marker(marker: str) -> None:
    completed = subprocess.run(
        ["/usr/bin/logger", marker],
        check=False,
        capture_output=True,
    )
    if completed.returncode != 0:
        raise AuditBundleError("fixture Seatbelt marker emission failed")


def _run_seatbelt_canary_child(
    measurement_nonce: str,
    scope: str,
    port: int,
) -> int:
    context = _fixture_sandbox_context()
    if (
        context is None
        or context["measurement_nonce"] != measurement_nonce
        or scope not in {"root_child", "descendant", "drain"}
        or port not in {
            _SEATBELT_ROOT_CANARY_PORT,
            _SEATBELT_CHILD_CANARY_PORT,
            _SEATBELT_DRAIN_CANARY_PORT,
        }
    ):
        raise AuditBundleError(
            "fixture Seatbelt child context is invalid"
        )
    os.execv(
        "/usr/bin/nc",
        [
            "nc",
            "-z",
            "-G",
            "1",
            "192.0.2.1",
            str(port),
        ],
    )
    raise AssertionError("native Seatbelt canary exec returned")


def _denied_native_canary(
    *,
    argv: Sequence[str],
) -> None:
    completed = subprocess.run(
        argv,
        cwd=ROOT,
        env=dict(os.environ),
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 1:
        raise AuditBundleError(
            "fixture Seatbelt native canary was not denied"
        )


def _run_seatbelt_canary_branch(measurement_nonce: str) -> int:
    context = _fixture_sandbox_context()
    if (
        context is None
        or context["measurement_nonce"] != measurement_nonce
    ):
        raise AuditBundleError(
            "fixture Seatbelt branch context is invalid"
        )
    _denied_native_canary(
        argv=(
            sys.executable,
            str(Path(__file__).resolve()),
            "--seatbelt-canary-child",
            measurement_nonce,
            "descendant",
            str(_SEATBELT_CHILD_CANARY_PORT),
        )
    )
    return 0


def _run_seatbelt_canaries(measurement_nonce: str) -> int:
    root_pid = os.getpid()
    _denied_native_canary(
        argv=(
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
        cwd=ROOT,
        env=dict(os.environ),
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0 or completed.stderr:
        raise AuditBundleError(
            "fixture Seatbelt descendant canary failed"
        )
    return root_pid


def _require_fixture_canary_gate(expected: bytes, *, stage: str) -> None:
    if sys.stdin.buffer.read(1) != expected:
        raise AuditBundleError(
            f"fixture Seatbelt canary {stage} gate is invalid"
        )


def _wait_for_fixture_marker_delivery(
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
        raise AuditBundleError(
            "fixture Seatbelt marker timeout is invalid"
        )
    missing_events = [
        name
        for name in required_markers
        if name not in marker_events
    ]
    if missing_events:
        raise AuditBundleError(
            "fixture Seatbelt marker registry is incomplete: "
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
            raise AuditBundleError(
                "fixture Seatbelt marker delivery is incomplete: "
                + ", ".join(missing)
            )


def _terminate_fixture_process_group(
    process: subprocess.Popen[bytes],
) -> None:
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def _process_group_is_quiescent(process_group_id: int) -> bool:
    try:
        os.killpg(process_group_id, 0)
    except ProcessLookupError:
        return True
    except PermissionError:
        return False
    return False


def _wait_for_process_group_exit(
    process_group_id: int,
    *,
    timeout_seconds: float = 10.0,
) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if _process_group_is_quiescent(process_group_id):
            return True
        time.sleep(0.05)
    return _process_group_is_quiescent(process_group_id)


def _run_fixture_drain_canary(
    *,
    sandbox_profile: str,
    measurement_nonce: str,
    environment: Mapping[str, str],
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
        cwd=ROOT,
        env=dict(environment),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    try:
        process_group_id = os.getpgid(canary.pid)
        if process_group_id != canary.pid:
            raise AuditBundleError(
                "fixture Seatbelt drain canary process group is invalid"
            )
        on_started(canary.pid)
        if canary.stdin is None:
            raise AuditBundleError(
                "fixture Seatbelt drain canary start gate is unavailable"
            )
        canary.stdin.write(b"1")
        canary.stdin.close()
        canary.stdin = None
        try:
            canary.communicate(timeout=10)
        except subprocess.TimeoutExpired as exc:
            raise AuditBundleError(
                "fixture Seatbelt drain canary timed out"
            ) from exc
        if canary.returncode != 1:
            raise AuditBundleError(
                "fixture Seatbelt drain canary was not denied"
            )
        if not _wait_for_process_group_exit(process_group_id):
            _terminate_fixture_process_group(canary)
            raise AuditBundleError(
                "fixture Seatbelt drain canary process group "
                "is not quiescent"
            )
        return canary.pid
    finally:
        if canary.poll() is None:
            _terminate_fixture_process_group(canary)


def _run_fixture_in_macos_sandbox(
    argv: Sequence[str],
    *,
    output: Path,
) -> int:
    executable = Path("/usr/bin/sandbox-exec")
    if sys.platform != "darwin" or not executable.is_file():
        raise AuditBundleError(
            "fixture browser requires macOS sandbox-exec"
        )
    if output.exists() or output.is_symlink():
        raise AuditBundleError(
            f"fixture browser output already exists: {output}"
        )
    measurement_nonce = secrets.token_hex(32)
    sandbox_profile = _fixture_sandbox_profile(measurement_nonce)
    sandbox_profile_sha256 = sha256(
        sandbox_profile.encode("utf-8")
    ).hexdigest()
    environment = dict(os.environ)
    environment[_FIXTURE_SANDBOX_ENV] = sandbox_profile_sha256
    environment[_FIXTURE_SANDBOX_NONCE_ENV] = measurement_nonce
    capture = _execute_fixture_sandbox_process(
        argv=tuple(argv),
        sandbox_profile=sandbox_profile,
        measurement_nonce=measurement_nonce,
        environment=environment,
    )
    child_returncode = capture.get("child_returncode")
    child_stdout = capture.get("child_stdout")
    child_stderr = capture.get("child_stderr")
    seatbelt_raw = capture.get("seatbelt_raw")
    logger_stderr = capture.get("logger_stderr")
    logger_returncode = capture.get("logger_returncode")
    sandbox_root_pid = capture.get("sandbox_root_pid")
    sandbox_process_group_id = capture.get(
        "sandbox_process_group_id"
    )
    process_group_quiescent = capture.get("process_group_quiescent")
    if (
        type(child_returncode) is not int
        or not isinstance(child_stdout, bytes)
        or not isinstance(child_stderr, bytes)
        or not isinstance(seatbelt_raw, bytes)
        or not isinstance(logger_stderr, bytes)
        or type(logger_returncode) is not int
        or type(sandbox_root_pid) is not int
        or type(sandbox_process_group_id) is not int
        or process_group_quiescent is not True
    ):
        raise AuditBundleError(
            "fixture sandbox execution result is invalid"
        )
    if child_returncode != 0:
        _publish_fixture_sandbox_failure(
            output=output,
            sandbox_profile=sandbox_profile,
            measurement_nonce=measurement_nonce,
            seatbelt_raw=seatbelt_raw,
            logger_stderr=logger_stderr,
            logger_returncode=logger_returncode,
            child_returncode=child_returncode,
            child_stderr=child_stderr,
        )
        if child_stderr:
            sys.stderr.buffer.write(child_stderr)
        return child_returncode
    if child_stderr:
        raise AuditBundleError(
            "fixture sandbox child wrote unexpected stderr"
        )
    child_report = _fixture_child_report(child_stdout)
    report = _finalize_fixture_sandbox_evidence(
        base_url=str(child_report.get("base_url", "")),
        output=output,
        child_report=child_report,
        sandbox_profile=sandbox_profile,
        measurement_nonce=measurement_nonce,
        seatbelt_raw=seatbelt_raw,
        logger_stderr=logger_stderr,
        logger_returncode=logger_returncode,
        sandbox_root_pid=sandbox_root_pid,
        sandbox_process_group_id=sandbox_process_group_id,
        process_group_quiescent=process_group_quiescent,
    )
    print(json.dumps(report, ensure_ascii=False))
    return 0


def _fixture_child_report(stdout: bytes) -> dict[str, Any]:
    try:
        text = stdout.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise AuditBundleError(
            "fixture sandbox child output is not UTF-8"
        ) from exc
    lines = [line for line in text.splitlines() if line]
    if len(lines) != 1:
        raise AuditBundleError(
            "fixture sandbox child output is invalid"
        )
    try:
        payload = json.loads(lines[0])
    except json.JSONDecodeError as exc:
        raise AuditBundleError(
            "fixture sandbox child output is invalid"
        ) from exc
    if not isinstance(payload, dict):
        raise AuditBundleError(
            "fixture sandbox child output is invalid"
        )
    return payload


def _seatbelt_log_predicate(measurement_nonce: str) -> str:
    if re.fullmatch(r"[0-9a-f]{64}", measurement_nonce) is None:
        raise AuditBundleError("fixture sandbox nonce is invalid")
    return f'eventMessage CONTAINS "{measurement_nonce}"'


def _execute_fixture_sandbox_process(
    *,
    argv: tuple[str, ...],
    sandbox_profile: str,
    measurement_nonce: str,
    environment: dict[str, str],
) -> dict[str, object]:
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
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if log_process.stdout is None or log_process.stderr is None:
        log_process.kill()
        raise AuditBundleError(
            "fixture Seatbelt logger pipes are unavailable"
        )
    raw_chunks: list[bytes] = []
    stderr_chunks: list[bytes] = []
    marker_events = {
        name: threading.Event()
        for name in (
            "ready",
            "begin",
            "root_child",
            "descendant",
            "end",
            "drain_canary",
            "drain",
        )
    }
    ready_observed = marker_events["ready"]
    preflight_denials_observed = threading.Event()
    kernel_denials: list[tuple[int, int]] = []
    kernel_denial_lock = threading.Lock()
    ready_marker = f"{_SEATBELT_READY_PREFIX}:{measurement_nonce}"
    drain_marker = f"{_SEATBELT_DRAIN_PREFIX}:{measurement_nonce}"
    marker_patterns = {
        "ready": re.compile(rf"^{re.escape(ready_marker)}$"),
        "begin": re.compile(
            rf"^{_SEATBELT_BEGIN_PREFIX}:{measurement_nonce}:\d+$"
        ),
        "root_child": re.compile(
            rf"^{_SEATBELT_CANARY_PREFIX}:{measurement_nonce}:"
            rf"root_child:\d+:{_SEATBELT_ROOT_CANARY_PORT}$"
        ),
        "descendant": re.compile(
            rf"^{_SEATBELT_CANARY_PREFIX}:{measurement_nonce}:"
            rf"descendant:\d+:{_SEATBELT_CHILD_CANARY_PORT}$"
        ),
        "end": re.compile(
            rf"^{_SEATBELT_END_PREFIX}:{measurement_nonce}:\d+$"
        ),
        "drain_canary": re.compile(
            rf"^{_SEATBELT_CANARY_PREFIX}:{measurement_nonce}:"
            rf"drain:\d+:{_SEATBELT_DRAIN_CANARY_PORT}$"
        ),
        "drain": re.compile(rf"^{re.escape(drain_marker)}$"),
    }
    denial_pattern = re.compile(
        r"^Sandbox: .+\((?P<pid>\d+)\) deny\(1\) "
        r"network-outbound remote:\*:(?P<port>\d+)\n"
        rf"{measurement_nonce}$"
    )

    def read_stdout() -> None:
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
                denial_match = denial_pattern.fullmatch(message)
                if denial_match is not None:
                    with kernel_denial_lock:
                        kernel_denials.append(
                            (
                                int(denial_match.group("pid")),
                                int(denial_match.group("port")),
                            )
                        )
                        ports = {port for _, port in kernel_denials}
                        if {
                            _SEATBELT_ROOT_CANARY_PORT,
                            _SEATBELT_CHILD_CANARY_PORT,
                        }.issubset(ports):
                            preflight_denials_observed.set()

    def read_stderr() -> None:
        for line in iter(log_process.stderr.readline, b""):
            stderr_chunks.append(line)

    stdout_thread = threading.Thread(
        target=read_stdout,
        name="task11-seatbelt-log-stdout",
    )
    stderr_thread = threading.Thread(
        target=read_stderr,
        name="task11-seatbelt-log-stderr",
    )
    stdout_thread.start()
    stderr_thread.start()
    child_returncode: int | None = None
    child_stdout = b""
    child_stderr = b""
    child_pid: int | None = None
    child: subprocess.Popen[bytes] | None = None
    process_group_id: int | None = None
    process_group_quiescent = False
    try:
        deadline = time.monotonic() + 10
        while not ready_observed.is_set():
            if log_process.poll() is not None:
                raise AuditBundleError(
                    "fixture Seatbelt logger exited before readiness"
                )
            _emit_seatbelt_marker(ready_marker)
            if ready_observed.wait(timeout=0.5):
                break
            if time.monotonic() >= deadline:
                break
        if not ready_observed.is_set():
            raise AuditBundleError(
                "fixture Seatbelt readiness marker was not observed"
            )
        child = subprocess.Popen(
            [
                "/usr/bin/sandbox-exec",
                "-p",
                sandbox_profile,
                sys.executable,
                str(Path(__file__).resolve()),
                *argv,
            ],
            cwd=ROOT,
            env=environment,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        child_pid = child.pid
        process_group_id = os.getpgid(child.pid)
        if process_group_id != child.pid:
            raise AuditBundleError(
                "fixture sandbox process group identity is invalid"
            )
        _emit_seatbelt_marker(
            f"{_SEATBELT_BEGIN_PREFIX}:{measurement_nonce}:{child_pid}"
        )
        _wait_for_fixture_marker_delivery(
            marker_events=marker_events,
            required_markers=("begin",),
        )
        if child.stdin is None:
            raise AuditBundleError(
                "fixture Seatbelt canary start gate is unavailable"
            )
        child.stdin.write(b"1")
        child.stdin.flush()
        if not preflight_denials_observed.wait(timeout=10):
            raise AuditBundleError(
                "fixture Seatbelt preflight denials were not observed"
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
            raise AuditBundleError(
                "fixture Seatbelt preflight canary identity is invalid"
            )
        root_child_pid = next(iter(root_child_pids))
        descendant_pid = next(iter(descendant_pids))
        _emit_seatbelt_marker(
            f"{_SEATBELT_CANARY_PREFIX}:{measurement_nonce}:"
            f"root_child:{root_child_pid}:{_SEATBELT_ROOT_CANARY_PORT}"
        )
        _emit_seatbelt_marker(
            f"{_SEATBELT_CANARY_PREFIX}:{measurement_nonce}:"
            f"descendant:{descendant_pid}:{_SEATBELT_CHILD_CANARY_PORT}"
        )
        _wait_for_fixture_marker_delivery(
            marker_events=marker_events,
            required_markers=("root_child", "descendant"),
        )
        child.stdin.write(b"2")
        child.stdin.close()
        child.stdin = None
        try:
            child_stdout, child_stderr = child.communicate(timeout=300)
        except subprocess.TimeoutExpired as exc:
            os.killpg(process_group_id, signal.SIGKILL)
            child_stdout, child_stderr = child.communicate(timeout=10)
            raise AuditBundleError(
                "fixture sandbox child exceeded runtime bound"
            ) from exc
        child_returncode = child.returncode
        process_group_quiescent = _wait_for_process_group_exit(
            process_group_id
        )
        if not process_group_quiescent:
            os.killpg(process_group_id, signal.SIGKILL)
            _wait_for_process_group_exit(process_group_id)
            raise AuditBundleError(
                "fixture sandbox process group is not quiescent"
            )
        if child_returncode == 0:
            def mark_drain_canary(pid: int) -> None:
                _emit_seatbelt_marker(
                    f"{_SEATBELT_CANARY_PREFIX}:{measurement_nonce}:"
                    f"drain:{pid}:{_SEATBELT_DRAIN_CANARY_PORT}"
                )
                _wait_for_fixture_marker_delivery(
                    marker_events=marker_events,
                    required_markers=("drain_canary",),
                )

            drain_canary_pid = _run_fixture_drain_canary(
                sandbox_profile=sandbox_profile,
                measurement_nonce=measurement_nonce,
                environment=environment,
                on_started=mark_drain_canary,
            )
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
                    raise AuditBundleError(
                        "fixture Seatbelt drain canary denial "
                        "was not observed"
                    )
                time.sleep(0.05)
        _emit_seatbelt_marker(
            f"{_SEATBELT_END_PREFIX}:{measurement_nonce}:{child_pid}"
        )
        _wait_for_fixture_marker_delivery(
            marker_events=marker_events,
            required_markers=("end",),
            timeout_seconds=10 if child_returncode == 0 else 2,
        )
        if child_returncode == 0:
            _emit_seatbelt_marker(drain_marker)
            _wait_for_fixture_marker_delivery(
                marker_events=marker_events,
                required_markers=("drain",),
            )
    finally:
        if child is not None and child.poll() is None:
            _terminate_fixture_process_group(child)
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
        raise AuditBundleError(
            "fixture Seatbelt logger did not drain cleanly"
        )
    if (
        child_returncode is None
        or child_pid is None
        or process_group_id is None
    ):
        raise AuditBundleError(
            "fixture sandbox child did not start"
        )
    return {
        "child_returncode": child_returncode,
        "child_stdout": child_stdout,
        "child_stderr": child_stderr,
        "sandbox_root_pid": child_pid,
        "sandbox_process_group_id": process_group_id,
        "process_group_quiescent": process_group_quiescent,
        "seatbelt_raw": b"".join(raw_chunks),
        "logger_stderr": b"".join(stderr_chunks),
        "logger_returncode": logger_returncode,
    }


@dataclass(frozen=True, slots=True)
class BoundedBrowserTurn:
    turn_id: str
    message: str
    expected_mode: str
    expected_recommendation_mode: str | None = None
    image_path: Path | None = None
    image_paths: tuple[Path, ...] = ()
    expected_image_product_id: int | None = None
    allow_clarification: bool = False


@dataclass(frozen=True, slots=True)
class BoundedBrowserTrajectory:
    trajectory_id: str
    turns: tuple[BoundedBrowserTurn, ...]
    release_mode: str | None = None


REQUIRED_TURN_FILES = frozenset({
    "request.json",
    "stream.sse",
    "presentation-contract.json",
    "terminal-dom.json",
    "screenshot.png",
    "console.json",
    "network.json",
})

FIXTURE_TURN_IDS = (
    "fixture-explore-recommendation",
    "fixture-fit-recommendation",
    "fixture-fit-clarification",
    "fixture-product-knowledge",
    "fixture-comparison",
    "fixture-image-identity",
    "fixture-image-fit-recommendation",
    "fixture-multi-image-comparison",
)

VIEWPORTS = {
    "desktop": {"width": 1440, "height": 1000},
    "mobile": {"width": 390, "height": 844},
}

BOUNDED_TRAJECTORIES = (
    BoundedBrowserTrajectory(
        trajectory_id="bounded-text-fit",
        turns=(
            BoundedBrowserTurn(
                turn_id="t1",
                message=(
                    "给我推荐一款最适合油敏肌、换季泛红的"
                    " 900 到 1100 元精华"
                ),
                expected_mode="recommendation",
                expected_recommendation_mode="fit",
                allow_clarification=True,
            ),
        ),
    ),
    BoundedBrowserTrajectory(
        trajectory_id="bounded-text-context",
        turns=(
            BoundedBrowserTurn(
                turn_id="t1",
                message="给我推荐 900 到 1100 元的精华",
                expected_mode="recommendation",
                expected_recommendation_mode="explore",
            ),
            BoundedBrowserTurn(
                turn_id="t2",
                message="第二款的质地适合什么肤质？",
                expected_mode="product_knowledge",
            ),
            BoundedBrowserTurn(
                turn_id="t3",
                message=(
                    "我现在有点换季泛红，T 区出油，"
                    "我可能是什么肤质？"
                ),
                expected_mode="consultation",
            ),
            BoundedBrowserTurn(
                turn_id="t4",
                message="确认",
                expected_mode="consultation",
            ),
            BoundedBrowserTurn(
                turn_id="t5",
                message=(
                    "回到刚才的推荐，第一款和第二款"
                    "哪个更适合我的肤质？"
                ),
                expected_mode="comparison",
            ),
        ),
    ),
    BoundedBrowserTrajectory(
        trajectory_id="bounded-image-context",
        turns=(
            BoundedBrowserTurn(
                turn_id="t1",
                message="",
                expected_mode="image_identity",
                image_path=(
                    ROOT
                    / "tests/fixtures/guide/images/"
                    "product-38-index-control.png"
                ),
                expected_image_product_id=38,
            ),
            BoundedBrowserTurn(
                turn_id="t2",
                message=(
                    "给我找两款相似的，我最近换季泛红，"
                    "T 区出油。"
                ),
                expected_mode="recommendation",
                expected_recommendation_mode="explore",
            ),
            BoundedBrowserTurn(
                turn_id="t3",
                message=(
                    "图片里的 B5 和第一款哪个更适合我的肤质？"
                ),
                expected_mode="comparison",
            ),
        ),
    ),
)

RELEASE_TRAJECTORIES = (
    BoundedBrowserTrajectory(
        trajectory_id="release-explore-recommendation",
        release_mode="explore_recommendation",
        turns=(
            BoundedBrowserTurn(
                turn_id="t1",
                message="给我推荐三款 900 到 1100 元的精华",
                expected_mode="recommendation",
                expected_recommendation_mode="explore",
            ),
        ),
    ),
    BoundedBrowserTrajectory(
        trajectory_id="release-fit-recommendation",
        release_mode="fit_recommendation",
        turns=(
            BoundedBrowserTurn(
                turn_id="t1",
                message=(
                    "给我推荐一款最适合油敏肌、换季泛红的"
                    " 900 到 1100 元精华"
                ),
                expected_mode="recommendation",
                expected_recommendation_mode="fit",
            ),
        ),
    ),
    BoundedBrowserTrajectory(
        trajectory_id="release-product-knowledge",
        release_mode="product_knowledge",
        turns=(
            BoundedBrowserTurn(
                turn_id="t1",
                message="理肤泉新B5多效修护精华的质地适合什么肤质？",
                expected_mode="product_knowledge",
            ),
        ),
    ),
    BoundedBrowserTrajectory(
        trajectory_id="release-comparison",
        release_mode="comparison",
        turns=(
            BoundedBrowserTurn(
                turn_id="t1",
                message=(
                    "理肤泉新B5多效修护精华和玉泽皮肤屏障"
                    "修护精华乳哪个更适合油敏肌？"
                ),
                expected_mode="comparison",
            ),
        ),
    ),
    BoundedBrowserTrajectory(
        trajectory_id="release-image-identity",
        release_mode="image_identity",
        turns=(
            BoundedBrowserTurn(
                turn_id="t1",
                message="",
                expected_mode="image_identity",
                image_path=(
                    ROOT
                    / "tests/fixtures/guide/images/"
                    "product-38-index-control.png"
                ),
                expected_image_product_id=38,
            ),
        ),
    ),
    BoundedBrowserTrajectory(
        trajectory_id="release-image-fit-recommendation",
        release_mode="image_fit_recommendation",
        turns=(
            BoundedBrowserTurn(
                turn_id="t1",
                message=(
                    "给我找一款最适合油敏肌、换季泛红时用的相似精华"
                ),
                expected_mode="recommendation",
                expected_recommendation_mode="fit",
                image_path=(
                    ROOT
                    / "tests/fixtures/guide/images/"
                    "product-38-index-control.png"
                ),
            ),
        ),
    ),
    BoundedBrowserTrajectory(
        trajectory_id="release-image-comparison",
        release_mode="image_comparison",
        turns=(
            BoundedBrowserTurn(
                turn_id="t1",
                message="比较这两张图里的商品",
                expected_mode="comparison",
                image_paths=(
                    ROOT
                    / "tests/fixtures/guide/images/"
                    "product-38-index-control.png",
                    ROOT
                    / "app/static/images/products/"
                    "jd_v3_10069603621835.png",
                ),
            ),
        ),
    ),
)

DEMO_TRAJECTORIES = (
    BoundedBrowserTrajectory(
        trajectory_id="demo-explore-recommendation",
        release_mode="explore_recommendation",
        turns=(
            BoundedBrowserTurn(
                turn_id="t1",
                message="预算三百以内，推荐适合海边的防晒",
                expected_mode="recommendation",
                expected_recommendation_mode="explore",
            ),
            BoundedBrowserTurn(
                turn_id="t2",
                message="第二款更适合油皮吗？",
                expected_mode="single_product",
            ),
            BoundedBrowserTurn(
                turn_id="t3",
                message="预算改成两百以内，其他要求不变",
                expected_mode="recommendation",
                expected_recommendation_mode="explore",
            ),
        ),
    ),
    BoundedBrowserTrajectory(
        trajectory_id="demo-fit-recommendation",
        release_mode="fit_recommendation",
        turns=(
            BoundedBrowserTurn(
                turn_id="t1",
                message=(
                    "给我推荐一款最适合修护屏障、清爽不黏需求的"
                    " 900 到 1100 元精华"
                ),
                expected_mode="recommendation",
                expected_recommendation_mode="fit",
            ),
            BoundedBrowserTurn(
                turn_id="t2",
                message=(
                    "功效仍然优先修护屏障，"
                    "但肤感改成更水润，还是只要一款"
                ),
                expected_mode="recommendation",
                expected_recommendation_mode="fit",
            ),
            BoundedBrowserTurn(
                turn_id="t3",
                message="预算降到八百，其他要求不变，还是只要一款",
                expected_mode="recommendation",
                expected_recommendation_mode="fit",
            ),
        ),
    ),
    BoundedBrowserTrajectory(
        trajectory_id="demo-product-knowledge",
        release_mode="product_knowledge",
        turns=(
            BoundedBrowserTurn(
                turn_id="t1",
                message="理肤泉新B5多效修护精华的质地适合什么肤质？",
                expected_mode="product_knowledge",
            ),
            BoundedBrowserTurn(
                turn_id="t2",
                message="它的主要功效方向呢？",
                expected_mode="product_knowledge",
            ),
            BoundedBrowserTurn(
                turn_id="t3",
                message="回到质地，它更偏清爽还是滋润？",
                expected_mode="product_knowledge",
            ),
        ),
    ),
    BoundedBrowserTrajectory(
        trajectory_id="demo-comparison",
        release_mode="comparison",
        turns=(
            BoundedBrowserTurn(
                turn_id="t1",
                message="帮我对比兰蔻小黑瓶和小棕瓶",
                expected_mode="comparison",
            ),
            BoundedBrowserTurn(
                turn_id="t2",
                message="那哪个更适合油敏肌？",
                expected_mode="comparison",
            ),
            BoundedBrowserTurn(
                turn_id="t3",
                message=(
                    "继续比较这两款，不考虑肤质，"
                    "只看功效、质地和价格"
                ),
                expected_mode="comparison",
            ),
        ),
    ),
    BoundedBrowserTrajectory(
        trajectory_id="demo-image-identity",
        release_mode="image_identity",
        turns=(
            BoundedBrowserTurn(
                turn_id="t1",
                message="",
                expected_mode="image_identity",
                image_path=(
                    ROOT
                    / "tests/fixtures/guide/images/"
                    "product-38-index-control.png"
                ),
                expected_image_product_id=38,
            ),
            BoundedBrowserTurn(
                turn_id="t2",
                message="图里这款叫什么，确认一下",
                expected_mode="product_knowledge",
            ),
            BoundedBrowserTurn(
                turn_id="t3",
                message="那它的质地和功效是什么？",
                expected_mode="product_knowledge",
            ),
        ),
    ),
    BoundedBrowserTrajectory(
        trajectory_id="demo-image-fit-recommendation",
        release_mode="image_fit_recommendation",
        turns=(
            BoundedBrowserTurn(
                turn_id="t1",
                message=(
                    "给我找一款最适合油敏肌、换季泛红时用的"
                    "相似精华"
                ),
                expected_mode="recommendation",
                expected_recommendation_mode="fit",
                image_path=(
                    ROOT
                    / "tests/fixtures/guide/images/"
                    "product-38-index-control.png"
                ),
                allow_clarification=True,
            ),
            BoundedBrowserTurn(
                turn_id="t2",
                message=(
                    "不考虑肤质，继续参考第一轮上传的图片，"
                    "只推荐一款修护屏障、清爽不黏的相似精华"
                ),
                expected_mode="recommendation",
                expected_recommendation_mode="fit",
            ),
            BoundedBrowserTurn(
                turn_id="t3",
                message="预算改成三百以内，其他要求不变，还是只要一款",
                expected_mode="recommendation",
                expected_recommendation_mode="fit",
            ),
        ),
    ),
    BoundedBrowserTrajectory(
        trajectory_id="demo-image-comparison",
        release_mode="image_comparison",
        turns=(
            BoundedBrowserTurn(
                turn_id="t1",
                message="比较这两张图里的商品",
                expected_mode="comparison",
                image_paths=(
                    ROOT
                    / "tests/fixtures/guide/images/"
                    "product-38-index-control.png",
                    ROOT
                    / "app/static/images/products/"
                    "jd_v3_10069603621835.png",
                ),
            ),
            BoundedBrowserTurn(
                turn_id="t2",
                message="第二张图里的商品质地怎么样？",
                expected_mode="product_knowledge",
            ),
            BoundedBrowserTurn(
                turn_id="t3",
                message="回到这两张，按功效、质地和价格比较",
                expected_mode="comparison",
            ),
        ),
    ),
)


def _prepare_fixture_turn_inputs(page, turn_id: str) -> None:
    product_38 = (
        ROOT
        / "tests/fixtures/guide/images/"
        "product-38-index-control.png"
    )
    image_inputs = {
        "fixture-image-identity": ("", (product_38,)),
        "fixture-image-fit-recommendation": (
            "给我找一款最适合油敏肌、换季泛红时用的相似精华",
            (product_38,),
        ),
        "fixture-multi-image-comparison": (
            "比较这两张图里的商品",
            (
                product_38,
                ROOT
                / "app/static/images/products/"
                "jd_v3_10069603621835.png",
            ),
        ),
    }
    message, image_paths = image_inputs.get(
        turn_id,
        (f"fixture:{turn_id}", ()),
    )
    if any(not path.is_file() for path in image_paths):
        raise AuditBundleError("fixture browser image input is missing")
    if image_paths:
        page.set_input_files(
            "#imageInput",
            [str(path) for path in image_paths],
        )
        page.wait_for_function(
            """expected => (
                document.querySelectorAll(
                    '#imagePreview .preview-item'
                ).length === expected
            )""",
            arg=len(image_paths),
            timeout=10_000,
        )
    if message:
        page.fill("#chatInput", message)


def _fixture_chromium_args(netlog_path: Path) -> list[str]:
    return [
        f"--log-net-log={netlog_path}",
        "--net-log-capture-mode=IncludeSensitive",
        "--disable-background-networking",
        "--disable-component-update",
        "--disable-default-apps",
        "--disable-sync",
        "--disable-quic",
        "--disable-features=AsyncDns,UseDnsHttpsSvcb",
        "--metrics-recording-only",
        "--no-first-run",
    ]


_FETCH_CAPTURE = r"""
(() => {
    window.__mainlineAuditCaptures = [];
    window.__mainlineAuditCaptureErrors = [];
    const originalFetch = window.fetch.bind(window);
    window.fetch = async (...args) => {
        const response = await originalFetch(...args);
        const request = args[0];
        const options = args[1] || {};
        const url = typeof request === 'string'
            ? request
            : (request?.url || '');
        if (!url.includes('/api/v1/chat/stream')) return response;
        response.clone().arrayBuffer().then(buffer => {
            const bytes = Array.from(new Uint8Array(buffer));
            const raw = new TextDecoder('utf-8', {fatal: true}).decode(buffer);
            const events = raw.split(/\n\n+/).map(block => {
                let event = 'message';
                const data = [];
                for (const line of block.split('\n')) {
                    if (line.startsWith('event: ')) {
                        event = line.slice(7).trim();
                    } else if (line.startsWith('data: ')) {
                        data.push(line.slice(6));
                    }
                }
                if (!data.length) return null;
                return {event, data: JSON.parse(data.join('\n'))};
            }).filter(Boolean);
            window.__mainlineAuditCaptures.push({
                url,
                method: options.method || 'GET',
                body: typeof options.body === 'string' ? options.body : null,
                bytes,
                events
            });
        }).catch(error => {
            window.__mainlineAuditCaptureErrors.push(String(error));
        });
        return response;
    };
})()
"""


def required_public_text(
    sections: tuple[object, ...],
) -> tuple[str, ...]:
    output: list[str] = []
    for section in sections:
        if not isinstance(section, dict):
            continue
        for value in (
            section.get("copy_text"),
            section.get("advisor_reason"),
        ):
            if isinstance(value, str) and value:
                output.append(value)
        direct_facts = section.get("direct_facts", ())
        if not isinstance(direct_facts, (list, tuple)):
            continue
        output.extend(
            value
            for item in direct_facts
            if isinstance(item, dict)
            and isinstance(
                value := item.get("display_value"),
                str,
            )
            and value
        )
    return tuple(output)


def _normalize_visible_text(value: str) -> str:
    return " ".join(value.split())


def validate_bounded_contract(
    contract: dict[str, Any],
    *,
    expected_mode: str,
    expected_recommendation_mode: str | None,
    expected_image_product_id: int | None,
    observations: tuple[dict[str, Any], ...],
    allow_clarification: bool = False,
    allow_fallback_copy: bool = False,
) -> None:
    """Reject production smoke output that falls back or changes its owner."""
    if contract.get("terminal_kind") == "clarification":
        if not allow_clarification:
            raise BoundedContractError(
                owner="planning_state",
                failure_code="unexpected_clarification",
                message="bounded smoke received unexpected clarification terminal",
            )
        clarification = contract.get("clarification")
        if (
            expected_mode != "recommendation"
            or expected_recommendation_mode != "fit"
            or not isinstance(clarification, dict)
            or clarification.get("intended_responsibility")
            != "recommendation"
            or clarification.get("intended_recommendation_mode") != "fit"
            or clarification.get("clarification_basis")
            != "fit_selection_evidence_gap"
            or clarification.get("fit_gap_stage")
            not in {
                "decision_selection",
                "public_fact_projection",
            }
            or clarification.get("fit_decision_status")
            not in {
                "SELECTED",
                "TIED_BY_BUSINESS_EVIDENCE",
                "INSUFFICIENT_FOR_WINNER",
                "NO_CANDIDATE",
            }
            or not isinstance(
                clarification.get("fit_candidate_count"),
                int,
            )
            or not isinstance(
                clarification.get("fit_evidence_ref_count"),
                int,
            )
            or not isinstance(
                clarification.get("fit_public_fact_count"),
                int,
            )
            or (
                clarification.get("fit_gap_stage")
                == "decision_selection"
                and clarification.get("fit_decision_status")
                == "SELECTED"
            )
            or (
                clarification.get("fit_gap_stage")
                == "public_fact_projection"
                and (
                    clarification.get("fit_decision_status")
                    != "SELECTED"
                    or clarification.get("fit_public_fact_count") != 0
                )
            )
        ):
            raise BoundedContractError(
                owner="planning_state",
                failure_code="invalid_fit_clarification",
                message="bounded smoke received invalid fit clarification",
            )
        return
    telemetry = contract.get("telemetry")
    if (
        not allow_fallback_copy
        and (
            not isinstance(telemetry, dict)
            or not successful_copy_provenance(
                copy_source=contract.get("copy_source"),
                fallback_reason=telemetry.get("fallback_reason"),
            )
        )
    ):
        raise BoundedContractError(
            owner="presentation_provenance",
            failure_code="fallback_copy",
            message="bounded smoke forbids fallback copy",
        )
    if contract.get("mode") != expected_mode:
        raise BoundedContractError(
            owner="planning_state",
            failure_code="presentation_mode_mismatch",
        )
    if (
        expected_recommendation_mode is not None
        and contract.get("recommendation_mode")
        != expected_recommendation_mode
    ):
        raise BoundedContractError(
            owner="planning_state",
            failure_code="recommendation_mode_mismatch",
        )
    if expected_image_product_id is None:
        return
    if len(observations) != 1:
        raise BoundedContractError(
            owner="retrieval_identity",
            failure_code="image_identity_count_mismatch",
        )
    observation = observations[0]
    if (
        observation.get("identity_state") != "confirmed"
        or observation.get("confirmed_product_id")
        != expected_image_product_id
    ):
        raise BoundedContractError(
            owner="retrieval_identity",
            failure_code="image_identity_mismatch",
        )


def fixture_sse_bytes(turn_id: str) -> bytes:
    """Return one deterministic, fully typed zero-API terminal stream."""
    if turn_id == "fixture-fit-clarification":
        events = (
            ("start", {"session_id": turn_id}),
            (
                "intent",
                {
                    "intent": "recommend",
                    "entities": {},
                    "scenario_intent": "recommend",
                    "guide": True,
                },
            ),
            (
                "clarify",
                {
                    "question": (
                        "现有公开事实还不能支持唯一选择。"
                        "请补充一个更明确的功效、肤感或使用场景，"
                        "或者改为查看多款方向。"
                    ),
                    "clarification_code": "goal",
                    "intended_responsibility": "recommendation",
                    "intended_recommendation_mode": "fit",
                    "clarification_basis": "fit_selection_evidence_gap",
                    "fit_gap_stage": "decision_selection",
                    "fit_decision_status": "INSUFFICIENT_FOR_WINNER",
                    "fit_candidate_count": 3,
                    "fit_evidence_ref_count": 9,
                    "fit_public_fact_count": 0,
                },
            ),
            ("end", {"conversation_version": 1}),
        )
        return b"".join(
            (
                f"event: {event}\n"
                "data: "
                f"{json.dumps(data, ensure_ascii=False, separators=(',', ':'))}"
                "\n\n"
            ).encode("utf-8")
            for event, data in events
        )
    contract = _fixture_contract(turn_id)
    products = tuple(
        _fixture_card(product_id)
        for product_id in contract.visible_product_ids
    )
    intent, decision_status = _fixture_terminal_shape(turn_id)
    image_comparison_data = (
        _fixture_image_comparison_data()
        if turn_id == "fixture-multi-image-comparison"
        else None
    )
    answer_status = (
        decision_status
        if decision_status is not None
        else "NOT_APPLICABLE"
    )
    events: list[tuple[str, dict[str, Any]]] = [
        ("start", {"session_id": turn_id}),
        (
            "intent",
            {
                "intent": intent,
                "entities": {},
                "scenario_intent": intent,
                "guide": True,
            },
        ),
        (
            "answer_contract",
            {
                "answer_contract": {
                    "product_count": len(products),
                    "winner_status": answer_status,
                    "has_unknown_skin": False,
                },
                "product_count": len(products),
                "winner_status": answer_status,
                "has_unknown_skin": False,
            },
        ),
        (
            "card_display_contract",
            contract.card_display.model_dump(mode="json"),
        ),
        (
            "products",
            {
                "cards": [
                    card.model_dump(mode="json")
                    for card in products
                ],
                "products": [
                    project_frontend_product(card)
                    for card in products
                ],
            },
        ),
    ]
    if turn_id == "fixture-multi-image-comparison":
        events.extend(
            (
                (
                    "image_observation",
                    {
                        "observation": _fixture_image_observation(
                            image_ordinal=1,
                            product_id=38,
                            alternate_product_id=91,
                        )
                    },
                ),
                (
                    "image_observation",
                    {
                        "observation": _fixture_image_observation(
                            image_ordinal=2,
                            product_id=91,
                            alternate_product_id=38,
                        )
                    },
                ),
            )
        )
    if decision_status is not None:
        step_data = {
            "winner_status": decision_status,
            "products": len(products),
        }
        if image_comparison_data is not None:
            step_data["outcome"] = image_comparison_data
        decision_data: dict[str, Any] = {
            "ordered_product_ids": list(
                contract.visible_product_ids
            ),
            "winner_status": decision_status,
            "evidence_refs": [],
            "decision_process": {
                "steps": [
                    {
                        "type": "decision",
                        "title": "执行后端筛选规则",
                        "description": "已按公开展示合同完成筛选。",
                        "data": step_data,
                    }
                ],
                "final_recommendation": None,
            },
        }
        if image_comparison_data is not None:
            decision_data["comparison_data"] = (
                image_comparison_data
            )
        events.append(
            (
                "decision_process",
                decision_data,
            )
        )
    events.extend(
        (
            (
                "presentation_contract",
                contract.model_dump(mode="json"),
            ),
            ("end", {"conversation_version": 1}),
        )
    )
    return b"".join(
        (
            f"event: {event}\n"
            f"data: {json.dumps(data, ensure_ascii=False, separators=(',', ':'))}\n\n"
        ).encode("utf-8")
        for event, data in events
    )


def _fixture_terminal_shape(
    turn_id: str,
) -> tuple[str, str | None]:
    mapping = {
        "fixture-explore-recommendation": (
            "recommend",
            "NOT_APPLICABLE",
        ),
        "fixture-fit-recommendation": ("recommend", "SELECTED"),
        "fixture-product-knowledge": ("knowledge", None),
        "fixture-comparison": ("comparison", "SELECTED"),
        "fixture-image-identity": ("image_identity", None),
        "fixture-image-fit-recommendation": (
            "image_recommend",
            "SELECTED",
        ),
        "fixture-multi-image-comparison": (
            "image_compare",
            "winner",
        ),
    }
    try:
        return mapping[turn_id]
    except KeyError as error:
        raise ValueError(f"unknown fixture turn: {turn_id}") from error


def _fixture_contract(turn_id: str) -> PublicPresentationContract:
    telemetry = CopywriterTelemetry(
        provider="fixture",
        model="deterministic",
        prompt_tokens=0,
        completion_tokens=0,
        total_tokens=0,
        latency_ms=0.0,
        fallback_reason=None,
    )
    if turn_id == "fixture-explore-recommendation":
        return _recommendation_contract(
            product_ids=(38, 91),
            fit=False,
            telemetry=telemetry,
        )
    if turn_id == "fixture-fit-recommendation":
        return _recommendation_contract(
            product_ids=(38,),
            fit=True,
            telemetry=telemetry,
        )
    if turn_id == "fixture-image-fit-recommendation":
        return _recommendation_contract(
            product_ids=(91,),
            fit=True,
            telemetry=telemetry,
        )
    if turn_id == "fixture-product-knowledge":
        return PublicPresentationContract(
            responsibility=Responsibility.PRODUCT_KNOWLEDGE,
            mode="product_knowledge",
            copy_source=_fixture_copy_source("product_knowledge"),
            sections=(
                PresentationSection(
                    kind="summary",
                    copy_text="我按你问的内容整理这款商品的相关信息。",
                ),
                PresentationSection(
                    kind="answer",
                    copy_text="品牌主打修护舒缓的使用方向。",
                    used_fact_ids=("fixture:38:brand_main",),
                ),
                PresentationSection(kind="full_cards"),
            ),
            visible_product_ids=(38,),
            card_display=_card_display("single", (38,)),
            telemetry=telemetry,
        )
    if turn_id == "fixture-image-identity":
        return PublicPresentationContract(
            responsibility=Responsibility.IMAGE_IDENTITY,
            mode="image_identity",
            copy_source=_fixture_copy_source("image_identity"),
            sections=(
                PresentationSection(
                    kind="observation",
                    copy_text="图片中的商品已确认，下面只展示已核对信息。",
                ),
                PresentationSection(
                    kind="product",
                    slot_id="p1",
                    product_id=38,
                    direct_facts=(
                        DirectFactComponent(
                            fact_id="fixture:38:brand_main",
                            label="品牌主打",
                            display_value="修护舒缓",
                        ),
                    ),
                ),
                PresentationSection(kind="full_cards"),
            ),
            visible_product_ids=(38,),
            card_display=_card_display("single", (38,)),
            telemetry=telemetry,
        )
    if turn_id == "fixture-comparison":
        return _comparison_contract(telemetry=telemetry)
    if turn_id == "fixture-multi-image-comparison":
        return _comparison_contract(telemetry=telemetry)
    raise ValueError(f"unknown fixture turn: {turn_id}")


def _recommendation_contract(
    *,
    product_ids: tuple[int, ...],
    fit: bool,
    telemetry: CopywriterTelemetry,
) -> PublicPresentationContract:
    sections: list[PresentationSection] = [
        PresentationSection(
            kind="summary",
            copy_text="先按修护方向和使用感受看这几款的差异。",
        )
    ]
    for index, product_id in enumerate(product_ids, start=1):
        sections.append(
            PresentationSection(
                kind="product",
                copy_text="品牌主打修护舒缓的使用方向。",
                used_fact_ids=(
                    f"fixture:{product_id}:brand_main",
                ),
                advisor_reason="更适合优先关注舒缓的人。",
                advisor_used_fact_ids=(
                    f"fixture:{product_id}:brand_main",
                ),
                slot_id=f"p{index}",
                product_id=product_id,
                direct_facts=(
                    DirectFactComponent(
                        fact_id=f"fixture:{product_id}:brand_main",
                        label="品牌主打",
                        display_value="修护舒缓",
                    ),
                ),
            )
        )
    if fit:
        product_id = product_ids[0]
        winner = WinnerPresentation(
            status="selected",
            winner_product_id=product_id,
            reason="综合当前需求，修护舒缓方向更贴合。",
            fact_ids=(f"fixture:{product_id}:brand_main",),
            dimension_ids=("brand_main",),
        )
        closing = PresentationSection(kind="closing")
        recommendation_mode = "fit"
    else:
        winner = WinnerPresentation(status="not_applicable")
        closing = PresentationSection(
            kind="closing",
            copy_text="可以再按当前最在意的一项继续收窄。",
        )
        recommendation_mode = "explore"
    sections.extend((closing, PresentationSection(kind="full_cards")))
    return PublicPresentationContract(
        responsibility=Responsibility.RECOMMENDATION,
        mode="recommendation",
        recommendation_mode=recommendation_mode,
        copy_source=_fixture_copy_source("recommendation"),
        sections=tuple(sections),
        winner=winner,
        visible_product_ids=product_ids,
        card_display=_card_display(
            "single" if len(product_ids) == 1 else "recommendation",
            product_ids,
        ),
        telemetry=telemetry,
    )


def _comparison_contract(
    *,
    telemetry: CopywriterTelemetry,
) -> PublicPresentationContract:
    product_ids = (38, 91)
    rows = (
        ComparisonRow(
            dimension_id="brand_main",
            label="品牌主打",
            cells=tuple(
                ComparisonCell(
                    product_id=product_id,
                    value="修护舒缓",
                    fact_ids=(f"fixture:{product_id}:brand_main",),
                    state="known",
                )
                for product_id in product_ids
            ),
        ),
        ComparisonRow(
            dimension_id="texture.refreshing",
            label="清爽肤感",
            cells=tuple(
                ComparisonCell(
                    product_id=product_id,
                    value="轻薄好吸收",
                    fact_ids=(f"fixture:{product_id}:texture",),
                    state="known",
                )
                for product_id in product_ids
            ),
        ),
        ComparisonRow(
            dimension_id="profile_match",
            label="当前画像匹配",
            cells=tuple(
                ComparisonCell(
                    product_id=product_id,
                    value="当前需求匹配",
                    fact_ids=(f"fixture:{product_id}:profile",),
                    state="known",
                )
                for product_id in product_ids
            ),
        ),
    )
    return PublicPresentationContract(
        responsibility=Responsibility.COMPARISON,
        mode="comparison",
        copy_source=_fixture_copy_source("comparison"),
        sections=(
            PresentationSection(
                kind="summary",
                copy_text="这两款的重点不同，直接看当前问题相关的差异。",
            ),
            PresentationSection(kind="comparison"),
            PresentationSection(kind="full_cards"),
        ),
        requested_comparison_dimensions=("texture.refreshing",),
        comparison_rows=rows,
        winner=WinnerPresentation(
            status="selected",
            winner_product_id=38,
            reason="综合当前对比维度，修护舒缓方向更贴合。",
            fact_ids=(
                "fixture:38:brand_main",
                "fixture:38:texture",
                "fixture:38:profile",
            ),
            dimension_ids=(
                "brand_main",
                "texture.refreshing",
                "profile_match",
            ),
        ),
        visible_product_ids=product_ids,
        card_display=_card_display("comparison", product_ids),
        telemetry=telemetry,
    )


def _fixture_copy_source(mode: str) -> str:
    source = deterministic_copy_source(
        mode=mode,
        copywriter_policy="eligible",
        has_authoritative_public_copy=True,
    )
    if source is None:
        raise AssertionError("fixture copy source must be deterministic")
    return source


@lru_cache(maxsize=4)
def _canonical_public_products(
    repo_root: Path = ROOT,
) -> _CanonicalPublicCatalog:
    canonical_root = repo_root / "data" / "canonical"
    products = CanonicalProductReader.from_files(
        manifest_path=canonical_root / "core_products_v1_manifest.json",
        products_path=canonical_root / "core_products_v1.jsonl",
    )
    display_assets = load_product_display_assets(
        manifest_path=repo_root / GUIDE_PRODUCT_DISPLAY_RELATIVE_PATH,
        expected_manifest_sha256=(
            GUIDE_PRODUCT_DISPLAY_MANIFEST_SHA256
        ),
    )
    images = load_seed_product_assets(
        manifest_path=(
            canonical_root / "seed_product_images_v1_manifest.json"
        ),
        products_path=canonical_root / "seed_product_images_v1.jsonl",
        asset_root=repo_root.resolve(),
    )
    category_facts = build_category_fact_reader(
        products,
        repo_root=repo_root,
    )
    catalog = CanonicalGuideCatalog(
        products,
        product_assets=images,
        category_fact_port=category_facts,
        product_display_bindings=ProductDisplayBindingReader(
            display_assets
        ),
    )
    allowed_variants = {
        product_id: {None}
        for product_id in products.product_ids
    }
    aliases = build_controlled_product_alias_registry(
        products,
        repo_root=repo_root,
    )
    for record in aliases.records:
        if record.variant_scope is None:
            continue
        for product_id in record.product_ids:
            allowed_variants[product_id].add(record.variant_scope)
    return _CanonicalPublicCatalog(
        catalog=catalog,
        product_ids=frozenset(products.product_ids),
        variant_scopes_by_product=MappingProxyType({
            product_id: frozenset(scopes)
            for product_id, scopes in allowed_variants.items()
        }),
    )


def _public_product_matches_canonical(
    product: Mapping[str, object],
) -> bool:
    try:
        actual = ProductCard.model_validate_json(
            json.dumps(product, ensure_ascii=False)
        )
    except (TypeError, ValueError):
        return False
    product_id = actual.product_id
    canonical = _canonical_public_products()
    if product_id not in canonical.product_ids:
        return False
    allowed_variants = canonical.variant_scopes_by_product.get(
        product_id,
        frozenset(),
    )
    if actual.variant_scope not in allowed_variants:
        return False
    actual_static = actual.model_dump(
        mode="json",
        exclude={"skin_match", "matched_efficacies"},
    )
    expected = None
    facts = None
    try:
        for variant_scope in sorted(
            allowed_variants,
            key=lambda item: item or "",
        ):
            candidate_facts = (
                canonical.catalog.get_presentation_facts(
                    product_id,
                    variant_scope=variant_scope,
                )
            )
            candidate = build_product_card(
                candidate_facts,
                skin_match="not_applicable",
                matched_efficacies=(),
            )
            if candidate.model_dump(
                mode="json",
                exclude={"skin_match", "matched_efficacies"},
            ) == actual_static:
                expected = candidate
                facts = candidate_facts
                break
    except (KeyError, RuntimeError, TypeError, ValueError):
        return False
    if expected is None or facts is None:
        return False
    canonical_efficacies = {
        value
        for fact in expected.category_facts
        if fact.field_key == "efficacy" and fact.state == "known"
        for value in (
            fact.value
            if isinstance(fact.value, tuple)
            else (fact.value,)
        )
        if isinstance(value, str)
    }
    if any(
        efficacy not in canonical_efficacies
        for efficacy in actual.matched_efficacies
    ):
        return False
    decision_facts = canonical.catalog.get_decision_facts(product_id)
    possible_skin_matches = {
        resolve_skin_match(decision_facts, None),
    }
    possible_skin_matches.update(
        resolve_skin_match(
            decision_facts,
            SkinConstraint(value=target),
        )
        for target in SkinTarget
    )
    return actual.skin_match in possible_skin_matches


def _product_payload_groups(
    events: Sequence[tuple[str, Mapping[str, object]]],
) -> tuple[
    tuple[Mapping[str, object], ...],
    tuple[Mapping[str, object], ...],
] | None:
    payloads = [
        payload for name, payload in events if name == "products"
    ]
    if not payloads:
        return ((), ())
    if len(payloads) != 1:
        return None
    raw_cards = payloads[0].get("cards")
    raw_products = payloads[0].get("products")
    if (
        not isinstance(raw_cards, list)
        or not isinstance(raw_products, list)
        or any(not isinstance(item, dict) for item in raw_cards)
        or any(not isinstance(item, dict) for item in raw_products)
    ):
        return None
    return tuple(raw_cards), tuple(raw_products)


def _product_payloads_match_canonical(
    *,
    events: Sequence[tuple[str, Mapping[str, object]]],
    expected_product_ids: Sequence[object],
) -> bool:
    groups = _product_payload_groups(events)
    if groups is None:
        return False
    cards, products = groups
    expected_ids = tuple(expected_product_ids)
    if not expected_ids:
        return not cards and not products
    try:
        typed_cards = tuple(
            ProductCard.model_validate_json(
                json.dumps(item, ensure_ascii=False)
            )
            for item in cards
        )
    except (TypeError, ValueError):
        return False
    return (
        tuple(card.product_id for card in typed_cards) == expected_ids
        and tuple(item.get("product_id") for item in products)
        == expected_ids
        and all(
            _public_product_matches_canonical(item) for item in cards
        )
        and tuple(
            project_frontend_product(card)
            for card in typed_cards
        )
        == products
    )


def _fixture_card(product_id: int) -> ProductCard:
    source = _canonical_public_products()
    if product_id not in source.product_ids:
        raise ValueError(f"unknown fixture product: {product_id}")
    return build_product_card(
        source.catalog.get_presentation_facts(product_id),
        skin_match="unknown",
        matched_efficacies=(),
    )


def _fixture_image_observation(
    *,
    image_ordinal: int,
    product_id: int,
    alternate_product_id: int,
) -> dict[str, Any]:
    return ImageIdentityObservation(
        image_id=f"image_{image_ordinal}{'f' * 32}",
        observation_state=ObservationState.PARTIAL,
        visual_state=VisualObservationState.OBSERVED,
        ocr_state=OcrObservationState.NOT_CONFIGURED,
        identity_state=IdentityState.CONFIRMED,
        confirmed_product_id=product_id,
        candidate_product_ids=(product_id, alternate_product_id),
        visual_confidence=0.99,
        similarity_margin=0.2,
        model_name="fixture-openclip",
        weights_sha256="a" * 64,
        preprocessing_version="fixture-preprocess-v1",
        vector_dimension=512,
        index_sha256="b" * 64,
        ocr_brand_consistency=IdentityEvidenceConsistency.NOT_CHECKED,
        ocr_product_name_consistency=(
            IdentityEvidenceConsistency.NOT_CHECKED
        ),
    ).model_dump(mode="json")


def _fixture_image_comparison_data() -> dict[str, Any]:
    references = [
        {
            "ordinal": 1,
            "image_id": f"image_1{'f' * 32}",
            "product_id": 38,
        },
        {
            "ordinal": 2,
            "image_id": f"image_2{'f' * 32}",
            "product_id": 91,
        },
    ]
    return {
        "status": "winner",
        "context_source": "current_upload",
        "references": references,
        "winner_reference": references[0],
        "tie_reason": None,
        "comparison_dimensions": ["price"],
        "evidence_refs": [],
        "evaluated_price_facts": [
            {
                "reference": references[0],
                "state": "known",
                "value": "294",
                "source_refs": [],
            },
            {
                "reference": references[1],
                "state": "known",
                "value": "88",
                "source_refs": [],
            },
        ],
    }


def _card_display(
    mode: str,
    product_ids: tuple[int, ...],
) -> CardDisplayContract:
    return CardDisplayContract(
        mode=mode,
        visible_product_ids=product_ids,
        max_cards=len(product_ids),
        reason=(
            "comparison"
            if mode == "comparison"
            else (
                "product"
                if mode == "single"
                else "recommendation"
            )
        ),
    )


def run_fixture_browser_audit(
    *,
    base_url: str,
    output: Path,
    viewport: str = "desktop",
    runtime_proof: _FixtureRuntimeProof | None = None,
    sandbox_profile: str | None = None,
    sandbox_root_pid: int | None = None,
) -> dict[str, Any]:
    """Render frontend fixture streams; this is not backend-path evidence."""
    if viewport not in VIEWPORTS:
        raise ValueError("fixture audit requires a concrete viewport")
    sandbox_values = (
        runtime_proof is not None,
        sandbox_profile is not None,
        sandbox_root_pid is not None,
    )
    if any(sandbox_values) and not all(sandbox_values):
        raise AuditBundleError(
            "fixture runtime and sandbox proof must be provided together"
        )
    if runtime_proof is not None and not _fixture_sandbox_active():
        raise AuditBundleError(
            "fixture browser is not running under the required sandbox"
        )
    from playwright.sync_api import sync_playwright

    output.mkdir(parents=True, exist_ok=False)
    netlog_path = output / "chromium-netlog.json"
    browser_requests: list[dict[str, str]] = []
    turn_directories: list[Path] = []
    if sandbox_profile is not None:
        (output / "sandbox-profile.sb").write_text(
            sandbox_profile,
            encoding="utf-8",
        )
    report: dict[str, Any] = {
        "schema_version": "guide-mainline-contract-browser-audit-v1",
        "trajectory_set": "fixture",
        "evidence_scope": FIXTURE_EVIDENCE_SCOPE,
        "backend_path_claim": FIXTURE_BACKEND_PATH_CLAIM,
        "base_url": base_url,
        "viewport": viewport,
        "turns": [],
        "invalid_clarification_count": 0,
    }
    if runtime_proof is not None:
        report.update(
            _persist_fixture_runtime_proof(
                output=output,
                proof=runtime_proof,
            )
        )
    executable = os.environ.get(
        "PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH"
    )
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            executable_path=executable or None,
            args=(
                _fixture_chromium_args(netlog_path)
                if runtime_proof is not None
                else []
            ),
        )
        try:
            for turn_id in FIXTURE_TURN_IDS:
                turn_dir = output / turn_id
                turn_dir.mkdir()
                turn_directories.append(turn_dir)
                context = browser.new_context(viewport=VIEWPORTS[viewport])
                page = context.new_page()
                _install_fixture_route(
                    page,
                    stream=fixture_sse_bytes(turn_id),
                )
                evidence = _browser_evidence(page)
                page.add_init_script(_FETCH_CAPTURE)
                page.goto(f"{base_url.rstrip('/')}/chat")
                _prepare_fixture_turn_inputs(page, turn_id)
                page.click("#sendBtn")
                _wait_for_fixture_terminal(page)
                _write_fixture_turn_bundle(
                    page=page,
                    turn_dir=turn_dir,
                    turn_id=turn_id,
                    viewport=viewport,
                    evidence=evidence,
                )
                validate_audit_bundle(
                    turn_dir,
                    expected_turn_id=turn_id,
                )
                report["turns"].append({
                    "turn_id": turn_id,
                    "directory": turn_dir.name,
                })
                context.close()
                browser_requests.extend(evidence["requests"])
        finally:
            browser.close()
    report["turn_count"] = len(report["turns"])
    report["passed"] = report["turn_count"] == len(FIXTURE_TURN_IDS)
    if (
        runtime_proof is not None
        and sandbox_profile is not None
        and sandbox_root_pid is not None
    ):
        report.update({
            "sandbox_root_pid": sandbox_root_pid,
            "browser_requests": browser_requests,
        })
    else:
        _write_json(output / "summary.json", report)
    return report


def run_fixture_browser_audits(
    *,
    base_url: str,
    output: Path,
    viewport: str,
    runtime_proof: _FixtureRuntimeProof | None = None,
    sandbox_profile: str | None = None,
    sandbox_root_pid: int | None = None,
) -> dict[str, Any]:
    """Run one fixture audit or the desktop and mobile evidence pair."""
    if viewport in VIEWPORTS:
        kwargs: dict[str, Any] = {
            "base_url": base_url,
            "output": output,
            "viewport": viewport,
        }
        if runtime_proof is not None:
            kwargs["runtime_proof"] = runtime_proof
            kwargs["sandbox_profile"] = sandbox_profile
            kwargs["sandbox_root_pid"] = sandbox_root_pid
        return run_fixture_browser_audit(
            **kwargs,
        )
    if viewport != "all":
        raise ValueError("fixture audit viewport is invalid")
    if runtime_proof is not None:
        raise AuditBundleError(
            "verified fixture audit requires one viewport per invocation"
        )

    output.mkdir(parents=True, exist_ok=False)
    reports: dict[str, dict[str, Any]] = {}
    for viewport_name in VIEWPORTS:
        reports[viewport_name] = run_fixture_browser_audit(
            base_url=base_url,
            output=output / viewport_name,
            viewport=viewport_name,
        )
    report: dict[str, Any] = {
        "schema_version": "guide-mainline-contract-browser-audit-v1",
        "trajectory_set": "fixture",
        "base_url": base_url,
        "viewport": "all",
        "reports": reports,
        "turn_count": sum(
            item["turn_count"] for item in reports.values()
        ),
        "invalid_clarification_count": sum(
            int(item.get("invalid_clarification_count", 0))
            for item in reports.values()
        ),
        "passed": all(
            item["passed"] for item in reports.values()
        ),
    }
    _write_json(output / "summary.json", report)
    return report


def run_bounded_browser_audit(
    *,
    base_url: str,
    output: Path,
    viewport: str,
    runtime_capability: str | None = None,
    trajectories: tuple[BoundedBrowserTrajectory, ...] = (
        BOUNDED_TRAJECTORIES
    ),
    trajectory_set: str = "bounded",
) -> dict[str, Any]:
    """Run the fixed paid smoke once and stop on its first failed turn."""
    if viewport not in VIEWPORTS:
        raise ValueError(
            "bounded smoke requires one concrete viewport"
        )
    from playwright.sync_api import sync_playwright

    output.mkdir(parents=True, exist_ok=False)
    report: dict[str, Any] = {
        "schema_version": "guide-mainline-contract-browser-audit-v1",
        "trajectory_set": trajectory_set,
        "base_url": base_url,
        "viewport": viewport,
        "trajectories": [],
        "turn_count": 0,
        "invalid_clarification_count": 0,
        "passed": False,
    }
    _write_json(output / "summary.json", report)
    executable = os.environ.get(
        "PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH"
    )
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            executable_path=executable or None,
        )
        try:
            for trajectory in trajectories:
                try:
                    trajectory_report = _run_bounded_browser_trajectory(
                        browser=browser,
                        base_url=base_url,
                        output=output,
                        trajectory=trajectory,
                        viewport=viewport,
                        runtime_capability=runtime_capability,
                        demo_usefulness=(
                            trajectory_set == "demo"
                        ),
                    )
                except AuditBundleError as error:
                    summary_path = (
                        output
                        / trajectory.trajectory_id
                        / "summary.json"
                    )
                    if summary_path.is_file():
                        failed_report = json.loads(
                            summary_path.read_text(encoding="utf-8")
                        )
                        report["trajectories"].append(failed_report)
                        report["turn_count"] += failed_report["turn_count"]
                        report["invalid_clarification_count"] += (
                            failed_report[
                                "invalid_clarification_count"
                            ]
                        )
                        _write_json(output / "summary.json", report)
                    completed_turns = int(
                        failed_report.get("turn_count", 0)
                    ) if summary_path.is_file() else 0
                    failed_turn = trajectory.turns[
                        min(completed_turns, len(trajectory.turns) - 1)
                    ]
                    evidence_directory = (
                        output
                        / trajectory.trajectory_id
                        / failed_turn.turn_id
                    )
                    raise BoundedAuditFailure(
                        turn_id=(
                            f"{trajectory.trajectory_id}-"
                            f"{failed_turn.turn_id}"
                        ),
                        owner=(
                            error.owner
                            if isinstance(error, BoundedContractError)
                            else _failure_owner_from_bundle(
                                evidence_directory
                            )
                        ),
                        failure_code=(
                            error.failure_code
                            if isinstance(error, BoundedContractError)
                            else type(error).__name__
                        ),
                        evidence_directory=evidence_directory,
                        message=str(error),
                    ) from error
                report["trajectories"].append(trajectory_report)
                report["turn_count"] += trajectory_report["turn_count"]
                report["invalid_clarification_count"] += (
                    trajectory_report["invalid_clarification_count"]
                )
                _write_json(output / "summary.json", report)
        finally:
            browser.close()
    report["passed"] = (
        len(report["trajectories"]) == len(trajectories)
        and report["turn_count"]
        == sum(
            len(trajectory.turns)
            for trajectory in trajectories
        )
    )
    _write_json(output / "summary.json", report)
    return report


def validate_completed_bounded_browser_evidence(
    output_directory: str | Path,
) -> dict[str, Any]:
    attempt_root = Path(output_directory).resolve()
    if not attempt_root.is_dir() or attempt_root.is_symlink():
        raise AuditBundleError(
            "bounded browser evidence is invalid"
        )
    summary_paths = tuple(
        sorted(attempt_root.glob("browser-*/summary.json"))
    )
    if len(summary_paths) != 1:
        raise AuditBundleError(
            "bounded browser evidence is invalid"
        )
    summary_path = summary_paths[0]
    browser_root = summary_path.parent
    summary = _read_object(summary_path)
    viewport = summary.get("viewport")
    trajectories = summary.get("trajectories")
    runtime_identity = attempt_root / RUNTIME_IDENTITY_FILENAME
    if (
        summary.get("schema_version")
        != "guide-mainline-contract-browser-audit-v1"
        or summary.get("trajectory_set") != "bounded"
        or viewport not in VIEWPORTS
        or summary.get("passed") is not True
        or summary.get("turn_count") != 9
        or summary.get("invalid_clarification_count") != 0
        or not isinstance(trajectories, list)
        or len(trajectories) != len(BOUNDED_TRAJECTORIES)
        or not runtime_identity.is_file()
        or runtime_identity.is_symlink()
        or summary.get("runtime_identity_sha256")
        != sha256(runtime_identity.read_bytes()).hexdigest()
        or re.fullmatch(
            r"[0-9a-f]{64}",
            str(summary.get("runtime_proof_sha256", "")),
        )
        is None
        or re.fullmatch(
            r"[0-9a-f]{64}",
            str(summary.get("runtime_attestation_sha256", "")),
        )
        is None
    ):
        raise AuditBundleError(
            "bounded browser evidence is invalid"
        )
    observed_trajectory_ids = tuple(
        row.get("trajectory_id")
        for row in trajectories
        if isinstance(row, dict)
    )
    expected_trajectory_ids = tuple(
        item.trajectory_id for item in BOUNDED_TRAJECTORIES
    )
    if observed_trajectory_ids != expected_trajectory_ids:
        raise AuditBundleError(
            "bounded browser evidence is invalid"
        )
    observed_turn_count = 0
    for trajectory, row in zip(
        BOUNDED_TRAJECTORIES,
        trajectories,
        strict=True,
    ):
        if not isinstance(row, dict):
            raise AuditBundleError(
                "bounded browser evidence is invalid"
            )
        turns = row.get("turns")
        if (
            not isinstance(turns, list)
            or row.get("turn_count") != len(trajectory.turns)
            or row.get("invalid_clarification_count") != 0
            or len(turns) != len(trajectory.turns)
        ):
            raise AuditBundleError(
                "bounded browser evidence is invalid"
            )
        for expected_turn, turn_row in zip(
            trajectory.turns,
            turns,
            strict=True,
        ):
            expected_relative = (
                Path(trajectory.trajectory_id) / expected_turn.turn_id
            )
            if (
                not isinstance(turn_row, dict)
                or turn_row.get("turn_id") != expected_turn.turn_id
                or turn_row.get("directory")
                != expected_relative.as_posix()
            ):
                raise AuditBundleError(
                    "bounded browser evidence is invalid"
                )
            turn_dir = (browser_root / expected_relative).resolve()
            if browser_root not in turn_dir.parents:
                raise AuditBundleError(
                    "bounded browser evidence is invalid"
                )
            expected_turn_id = (
                f"{trajectory.trajectory_id}-{expected_turn.turn_id}"
            )
            validate_audit_bundle(
                turn_dir,
                expected_turn_id=expected_turn_id,
            )
            request = _read_object(turn_dir / "request.json")
            if (
                request.get("user_message") != expected_turn.message
                or request.get("viewport") != VIEWPORTS[viewport]
            ):
                raise AuditBundleError(
                    "bounded browser evidence is invalid"
                )
            events = _sse_events_from_sse(
                (turn_dir / "stream.sse").read_text(encoding="utf-8")
            )
            contract = _read_object(
                turn_dir / "presentation-contract.json"
            )
            observations = tuple(
                payload["observation"]
                for event, payload in events
                if (
                    event == "image_observation"
                    and isinstance(payload.get("observation"), dict)
                )
            )
            validate_bounded_contract(
                contract,
                expected_mode=expected_turn.expected_mode,
                expected_recommendation_mode=(
                    expected_turn.expected_recommendation_mode
                ),
                expected_image_product_id=(
                    expected_turn.expected_image_product_id
                ),
                observations=observations,
                allow_clarification=expected_turn.allow_clarification,
            )
            observed_turn_count += 1
    actual_index = _artifact_sha256_by_path(
        browser_root,
        excluded={summary_path},
    )
    if (
        observed_turn_count != 9
        or summary.get("artifact_sha256_by_path") != actual_index
    ):
        raise AuditBundleError(
            "bounded browser evidence is invalid"
        )
    return summary


def validate_completed_release_browser_evidence(
    output_directory: str | Path,
    *,
    repo_root: Path = ROOT,
) -> dict[str, Any]:
    attempt_root = Path(output_directory).resolve()
    summary_path = attempt_root / "mainline-browser/summary.json"
    if (
        not attempt_root.is_dir()
        or attempt_root.is_symlink()
        or not summary_path.is_file()
        or summary_path.is_symlink()
    ):
        raise AuditBundleError("release browser evidence is invalid")
    summary = _read_object(summary_path)
    counter_keys = (
        "serious_failure_count",
        "frontend_contract_violation_count",
        "wrong_binding_count",
        "unaligned_price_specification_count",
        "copywriter_fallback_count",
        "invalid_clarification_count",
    )
    expected_turns: list[dict[str, object]] = []
    observed_counters = {key: 0 for key in counter_keys}
    for viewport in VIEWPORTS:
        browser_root = attempt_root / f"browser-{viewport}"
        viewport_summary_path = browser_root / "summary.json"
        if (
            not browser_root.is_dir()
            or browser_root.is_symlink()
            or not viewport_summary_path.is_file()
            or viewport_summary_path.is_symlink()
        ):
            raise AuditBundleError(
                "release browser evidence is invalid"
            )
        viewport_summary = _read_object(viewport_summary_path)
        trajectories = viewport_summary.get("trajectories")
        if (
            viewport_summary.get("schema_version")
            != "guide-mainline-contract-browser-audit-v1"
            or viewport_summary.get("trajectory_set") != "release"
            or viewport_summary.get("viewport") != viewport
            or viewport_summary.get("passed") is not True
            or viewport_summary.get("turn_count")
            != len(RELEASE_TRAJECTORIES)
            or viewport_summary.get("invalid_clarification_count") != 0
            or not isinstance(trajectories, list)
            or len(trajectories) != len(RELEASE_TRAJECTORIES)
        ):
            raise AuditBundleError(
                "release browser evidence is invalid"
            )
        by_id = {
            item.get("trajectory_id"): item
            for item in trajectories
            if isinstance(item, dict)
        }
        if set(by_id) != {
            item.trajectory_id for item in RELEASE_TRAJECTORIES
        }:
            raise AuditBundleError(
                "release browser evidence is invalid"
            )
        for trajectory in RELEASE_TRAJECTORIES:
            trajectory_report = by_id[trajectory.trajectory_id]
            turns = trajectory_report.get("turns")
            if (
                trajectory.release_mode is None
                or not isinstance(turns, list)
                or len(trajectory.turns) != 1
                or trajectory_report.get("turn_count") != 1
                or trajectory_report.get(
                    "invalid_clarification_count"
                )
                != 0
                or len(turns) != 1
            ):
                raise AuditBundleError(
                    "release browser evidence is invalid"
                )
            turn = trajectory.turns[0]
            turn_row = turns[0]
            expected_relative = (
                Path(trajectory.trajectory_id) / turn.turn_id
            )
            if (
                not isinstance(turn_row, dict)
                or turn_row.get("turn_id") != turn.turn_id
                or turn_row.get("directory")
                != expected_relative.as_posix()
            ):
                raise AuditBundleError(
                    "release browser evidence is invalid"
                )
            turn_dir = (browser_root / expected_relative).resolve()
            if browser_root.resolve() not in turn_dir.parents:
                raise AuditBundleError(
                    "release browser evidence is invalid"
                )
            validate_audit_bundle(
                turn_dir,
                expected_turn_id=(
                    f"{trajectory.trajectory_id}-{turn.turn_id}"
                ),
            )
            request = _read_object(turn_dir / "request.json")
            if (
                request.get("user_message") != turn.message
                or request.get("viewport") != VIEWPORTS[viewport]
            ):
                raise AuditBundleError(
                    "release browser evidence is invalid"
                )
            turn_counters = turn_row.get("release_counters")
            derived_counters = derive_release_turn_counters(
                turn_dir,
                allow_clarification=turn.allow_clarification,
            )
            if (
                not isinstance(turn_counters, dict)
                or set(turn_counters) != set(counter_keys)
                or any(
                    type(value) is not int or value != 0
                    for value in turn_counters.values()
                )
                or turn_counters != derived_counters
            ):
                raise AuditBundleError(
                    "release browser counters are invalid"
                )
            for key in counter_keys:
                observed_counters[key] += derived_counters[key]
            expected_turns.append({
                "viewport": viewport,
                "mode": trajectory.release_mode,
                "turn_id": (
                    f"{trajectory.trajectory_id}-{turn.turn_id}"
                ),
                "directory": (
                    Path(f"browser-{viewport}") / expected_relative
                ).as_posix(),
            })
    actual_artifacts = {
        path.relative_to(repo_root.resolve()).as_posix(): sha256(
            path.read_bytes()
        ).hexdigest()
        for directory in (
            attempt_root / "browser-desktop",
            attempt_root / "browser-mobile",
            attempt_root / "mainline-browser",
        )
        for path in sorted(directory.rglob("*"))
        if path.is_file() and path != summary_path
    }
    if (
        summary.get("schema_version")
        != "guide-mainline-contract-browser-audit-v1"
        or summary.get("trajectory_set") != "release"
        or summary.get("viewport") != "all"
        or summary.get("turns") != expected_turns
        or summary.get("turn_count") != 14
        or any(summary.get(key) != value for key, value in observed_counters.items())
        or summary.get("artifact_sha256") != actual_artifacts
        or summary.get("passed") is not True
        or re.fullmatch(
            r"[0-9a-f]{64}",
            str(summary.get("runtime_identity_sha256", "")),
        )
        is None
        or re.fullmatch(
            r"[0-9a-f]{64}",
            str(summary.get("runtime_proof_sha256", "")),
        )
        is None
        or re.fullmatch(
            r"[0-9a-f]{64}",
            str(summary.get("runtime_attestation_sha256", "")),
        )
        is None
    ):
        raise AuditBundleError("release browser evidence is invalid")
    return summary


def _failure_owner_from_bundle(turn_dir: Path) -> str:
    contract_path = turn_dir / "presentation-contract.json"
    if not contract_path.is_file():
        return "sse_contract"
    try:
        contract = _read_object(contract_path)
    except AuditBundleError:
        return "sse_contract"
    if contract.get("terminal_kind") == "error":
        return "sse_contract"
    if contract.get("terminal_kind") == "clarification":
        return "planning_state"
    if contract.get("copy_source") == "fallback":
        return "presentation_provenance"
    if (turn_dir / "terminal-dom.json").is_file():
        return "dom_rendering"
    return "sse_contract"


def _record_browser_runner_failure(
    *,
    output: Path,
    error: BaseException,
    failure_turn_id: str,
) -> Path:
    if output.is_symlink():
        raise AuditBundleError(
            "browser runner failure evidence path is invalid"
        )
    try:
        output.mkdir(parents=False, exist_ok=False)
    except FileExistsError:
        if output.is_symlink() or not output.is_dir():
            raise AuditBundleError(
                "browser runner failure evidence path is invalid"
            )
    _write_json_exclusive(
        output / "runner-failure.json",
        {
            "schema_version": "guide-browser-runner-failure-v1",
            "failure_turn_id": failure_turn_id,
            "error_type": type(error).__name__,
            "error_message": str(error),
        },
        label="browser runner failure evidence",
    )
    return output


def run_authorized_bounded_browser_audit(
    *,
    base_url: str,
    attempt_context: str | Path,
    viewport: str,
    expected_manifest_sha256: str,
) -> dict[str, Any]:
    context_path = Path(attempt_context)
    raw_context = _read_object(context_path)
    ledger_path = Path(str(raw_context.get("ledger_path")))
    readiness_path = Path(str(raw_context.get("readiness_path")))
    context = read_attempt_context(
        context_path,
        ledger_path=ledger_path,
        readiness_path=readiness_path,
    )
    verify_task11_readiness(
        readiness_path=readiness_path,
        ledger_path=ledger_path,
        expected_manifest_sha256=expected_manifest_sha256,
    )
    runtime_proof = consume_runtime_bound_attempt(
        context_path,
        phase="bounded",
        ledger_path=ledger_path,
        readiness_path=readiness_path,
        base_url=base_url,
    )
    output = Path(str(context["output_directory"])) / (
        f"browser-{viewport}"
    )
    try:
        report = run_bounded_browser_audit(
            base_url=base_url,
            output=output,
            viewport=viewport,
            runtime_capability=runtime_proof["runtime_proof_sha256"],
        )
        if (
            report.get("passed") is not True
            or report.get("invalid_clarification_count") != 0
        ):
            raise AuditBundleError(
                "bounded smoke result failed"
            )
        report.update(runtime_proof)
        report["artifact_sha256_by_path"] = _artifact_sha256_by_path(
            output,
            excluded={output / "summary.json"},
        )
        _write_json(output / "summary.json", report)
    except BoundedAuditFailure as error:
        complete_attempt(
            context_path,
            result="failed",
            first_failure_turn_id=error.turn_id,
            first_failure_owner=error.owner,
            failure_code=error.failure_code,
            evidence_directory=str(error.evidence_directory),
        )
        raise
    except BaseException as error:
        evidence_directory = _record_browser_runner_failure(
            output=output,
            error=error,
            failure_turn_id="bounded-runner-startup",
        )
        complete_attempt(
            context_path,
            result="failed",
            first_failure_turn_id="bounded-runner-startup",
            first_failure_owner="browser_audit",
            failure_code=type(error).__name__,
            evidence_directory=str(evidence_directory),
        )
        raise
    complete_attempt(context_path, result="passed")
    return report


def run_release_browser_audit(
    *,
    base_url: str,
    output: Path,
    viewport: str,
    runtime_capability: str | None = None,
    repo_root: Path = ROOT,
) -> dict[str, Any]:
    if viewport != "all":
        raise AuditBundleError(
            "release audit requires desktop and mobile"
        )
    browser_outputs = {
        name: output / f"browser-{name}"
        for name in VIEWPORTS
    }
    mainline_directory = output / "mainline-browser"
    if (
        mainline_directory.exists()
        or mainline_directory.is_symlink()
        or any(
            path.exists() or path.is_symlink()
            for path in browser_outputs.values()
        )
    ):
        raise AuditBundleError(
            "release browser output already exists"
        )
    reports = {
        name: run_bounded_browser_audit(
            base_url=base_url,
            output=browser_outputs[name],
            viewport=name,
            trajectories=RELEASE_TRAJECTORIES,
            trajectory_set="release",
            runtime_capability=runtime_capability,
        )
        for name in VIEWPORTS
    }
    turns: list[dict[str, object]] = []
    counter_keys = (
        "serious_failure_count",
        "frontend_contract_violation_count",
        "wrong_binding_count",
        "unaligned_price_specification_count",
        "copywriter_fallback_count",
        "invalid_clarification_count",
    )
    counters = {key: 0 for key in counter_keys}
    for viewport_name, viewport_report in reports.items():
        by_id = {
            row["trajectory_id"]: row
            for row in viewport_report["trajectories"]
        }
        for trajectory in RELEASE_TRAJECTORIES:
            trajectory_report = by_id.get(trajectory.trajectory_id)
            if (
                trajectory.release_mode is None
                or not isinstance(trajectory_report, dict)
                or len(trajectory_report.get("turns", ())) != 1
            ):
                raise AuditBundleError(
                    "release browser trajectory evidence is invalid"
                )
            turn_row = trajectory_report["turns"][0]
            relative = (
                Path(f"browser-{viewport_name}")
                / str(turn_row["directory"])
            )
            turn_dir = output / relative
            contract = _read_object(
                turn_dir / "presentation-contract.json"
            )
            turn_counters = turn_row.get("release_counters")
            if (
                not isinstance(turn_counters, dict)
                or set(turn_counters) != set(counter_keys)
                or any(
                    isinstance(value, bool)
                    or not isinstance(value, int)
                    or value < 0
                    for value in turn_counters.values()
                )
            ):
                raise AuditBundleError(
                    "release browser counters are invalid"
                )
            for key in counter_keys:
                counters[key] += turn_counters[key]
            turns.append({
                "viewport": viewport_name,
                "mode": trajectory.release_mode,
                "turn_id": (
                    f"{trajectory.trajectory_id}-"
                    f"{turn_row['turn_id']}"
                ),
                "directory": relative.as_posix(),
            })
    mainline_directory.mkdir(parents=True, exist_ok=False)
    summary_path = mainline_directory / "summary.json"
    report: dict[str, Any] = {
        "schema_version": "guide-mainline-contract-browser-audit-v1",
        "trajectory_set": "release",
        "base_url": base_url,
        "viewport": "all",
        "turns": turns,
        "turn_count": len(turns),
        **counters,
        "passed": (
            len(turns) == 14
            and all(item.get("passed") is True for item in reports.values())
            and not any(counters.values())
        ),
    }
    report["artifact_sha256"] = {
        path.relative_to(repo_root.resolve()).as_posix(): sha256(
            path.read_bytes()
        ).hexdigest()
        for directory in (
            browser_outputs["desktop"],
            browser_outputs["mobile"],
            mainline_directory,
        )
        for path in sorted(directory.rglob("*"))
        if path.is_file() and path != summary_path
    }
    _write_json(summary_path, report)
    if report["passed"] is not True:
        raise AuditBundleError("release browser audit failed")
    return report


def run_authorized_release_browser_audit(
    *,
    base_url: str,
    attempt_context: str | Path,
    viewport: str,
    expected_manifest_sha256: str,
) -> dict[str, Any]:
    if viewport != "all":
        raise AuditBundleError(
            "release audit requires desktop and mobile"
        )
    context_path = Path(attempt_context)
    raw_context = _read_object(context_path)
    ledger_path = Path(str(raw_context.get("ledger_path")))
    readiness_path = Path(str(raw_context.get("readiness_path")))
    context = read_attempt_context(
        context_path,
        ledger_path=ledger_path,
        readiness_path=readiness_path,
    )
    verify_task11_readiness(
        readiness_path=readiness_path,
        ledger_path=ledger_path,
        expected_manifest_sha256=expected_manifest_sha256,
    )
    runtime_proof = consume_runtime_bound_attempt(
        context_path,
        phase="browser",
        ledger_path=ledger_path,
        readiness_path=readiness_path,
        base_url=base_url,
    )
    output = Path(str(context["output_directory"])).resolve()
    try:
        report = run_release_browser_audit(
            base_url=base_url,
            output=output,
            viewport=viewport,
            runtime_capability=runtime_proof["runtime_proof_sha256"],
        )
        report.update(runtime_proof)
        _write_json(output / "mainline-browser/summary.json", report)
    except BoundedAuditFailure as error:
        complete_attempt(
            context_path,
            result="failed",
            first_failure_turn_id=error.turn_id,
            first_failure_owner=error.owner,
            failure_code=error.failure_code,
            evidence_directory=str(error.evidence_directory),
        )
        raise
    except BaseException as error:
        evidence_directory = _record_browser_runner_failure(
            output=output,
            error=error,
            failure_turn_id="release-browser-startup",
        )
        complete_attempt(
            context_path,
            result="failed",
            first_failure_turn_id="release-browser-startup",
            first_failure_owner="browser_audit",
            failure_code=type(error).__name__,
            evidence_directory=str(evidence_directory),
        )
        raise
    complete_attempt(context_path, result="passed")
    return report


def resolve_cli_output(
    *,
    trajectory_set: str,
    output: Path | None,
    attempt_context: Path | None,
) -> Path:
    if trajectory_set in {"fixture", "demo"}:
        if output is None:
            raise AuditBundleError(
                f"{trajectory_set} requires --output"
            )
        if attempt_context is not None:
            raise AuditBundleError(
                f"{trajectory_set} forbids --attempt-context"
            )
        return output
    if attempt_context is None:
        raise AuditBundleError(
            f"{trajectory_set} requires --attempt-context"
        )
    if output is not None:
        raise AuditBundleError(
            f"{trajectory_set} forbids --output"
        )
    return attempt_context


def _run_bounded_browser_trajectory(
    *,
    browser,
    base_url: str,
    output: Path,
    trajectory: BoundedBrowserTrajectory,
    viewport: str,
    runtime_capability: str | None = None,
    demo_usefulness: bool = False,
) -> dict[str, Any]:
    trajectory_dir = output / trajectory.trajectory_id
    trajectory_dir.mkdir()
    context_kwargs: dict[str, object] = {
        "viewport": VIEWPORTS[viewport],
    }
    if runtime_capability is not None:
        context_kwargs["extra_http_headers"] = {
            "X-Task11-Runtime-Proof": runtime_capability,
        }
    context = browser.new_context(**context_kwargs)
    page = context.new_page()
    page.add_init_script(_FETCH_CAPTURE)
    evidence = _browser_evidence(page)
    page.goto(f"{base_url.rstrip('/')}/chat")
    report: dict[str, Any] = {
        "trajectory_id": trajectory.trajectory_id,
        "turns": [],
        "turn_count": 0,
        "invalid_clarification_count": 0,
    }
    _write_json(trajectory_dir / "summary.json", report)
    try:
        for turn in trajectory.turns:
            turn_dir = trajectory_dir / turn.turn_id
            turn_dir.mkdir()
            capture_count = _capture_count(page)
            evidence_offsets = {
                name: len(items)
                for name, items in evidence.items()
            }
            image_paths = (
                turn.image_paths
                if turn.image_paths
                else (
                    (turn.image_path,)
                    if turn.image_path is not None
                    else ()
                )
            )
            if image_paths:
                if any(not path.is_file() for path in image_paths):
                    raise AuditBundleError(
                        "bounded smoke image fixture is missing"
                    )
                page.set_input_files(
                    "#imageInput",
                    [str(path) for path in image_paths],
                )
                page.wait_for_function(
                    """expected => (
                        document.querySelectorAll(
                            '#imagePreview .preview-item'
                        ).length === expected
                    )""",
                    arg=len(image_paths),
                    timeout=10_000,
                )
            if turn.message:
                page.fill("#chatInput", turn.message)
            page.click("#sendBtn")
            _wait_for_live_terminal(
                page,
                expected_capture_count=capture_count + 1,
            )
            turn_evidence = {
                name: items[evidence_offsets[name]:]
                for name, items in evidence.items()
            }
            contract, observations = _write_live_turn_bundle(
                page=page,
                turn_dir=turn_dir,
                trajectory_id=trajectory.trajectory_id,
                turn=turn,
                viewport=viewport,
                capture_index=capture_count,
                evidence=turn_evidence,
            )
            validate_audit_bundle(
                turn_dir,
                expected_turn_id=(
                    f"{trajectory.trajectory_id}-{turn.turn_id}"
                ),
            )
            try:
                validate_bounded_contract(
                    contract,
                    expected_mode=turn.expected_mode,
                    expected_recommendation_mode=(
                        turn.expected_recommendation_mode
                    ),
                    expected_image_product_id=(
                        turn.expected_image_product_id
                    ),
                    observations=observations,
                    allow_clarification=turn.allow_clarification,
                    allow_fallback_copy=demo_usefulness,
                )
                if demo_usefulness:
                    _validate_demo_usefulness(
                        contract=contract,
                        events=_sse_events_from_sse(
                            (turn_dir / "stream.sse").read_text(
                                encoding="utf-8"
                            )
                        ),
                    )
            except AuditBundleError:
                if contract.get("terminal_kind") == "clarification":
                    report["invalid_clarification_count"] += 1
                    _write_json(
                        trajectory_dir / "summary.json",
                        report,
                    )
                raise
            if turn_evidence["console"] or turn_evidence["network"]:
                raise AuditBundleError(
                    "bounded smoke browser telemetry failure"
                )
            report["turns"].append({
                "turn_id": turn.turn_id,
                "directory": str(
                    turn_dir.relative_to(output)
                ),
                "release_counters": derive_release_turn_counters(
                    turn_dir,
                    allow_clarification=turn.allow_clarification,
                ),
            })
            report["turn_count"] += 1
            _write_json(trajectory_dir / "summary.json", report)
    finally:
        context.close()
    return report


def derive_release_turn_counters(
    turn_dir: Path,
    *,
    allow_clarification: bool = False,
) -> dict[str, int]:
    keys = (
        "frontend_contract_violation_count",
        "wrong_binding_count",
        "unaligned_price_specification_count",
        "copywriter_fallback_count",
        "invalid_clarification_count",
    )
    counters = {key: 0 for key in keys}
    try:
        contract = _read_object(
            turn_dir / "presentation-contract.json"
        )
        dom = _read_object(turn_dir / "terminal-dom.json")
        events = _sse_events_from_sse(
            (turn_dir / "stream.sse").read_text(encoding="utf-8")
        )
        _validate_success_stream_lifecycle(events)
        _validate_stream_terminal_ownership(
            events,
            clarification=(
                contract.get("terminal_kind") == "clarification"
            ),
        )
        console = _read_list(turn_dir / "console.json")
        network = _read_list(turn_dir / "network.json")
    except (AuditBundleError, OSError, UnicodeError):
        counters["frontend_contract_violation_count"] = 1
        return {"serious_failure_count": 1, **counters}

    terminal_kind = contract.get("terminal_kind")
    if terminal_kind == "clarification":
        counters["invalid_clarification_count"] = int(
            not allow_clarification
        )
        counters["frontend_contract_violation_count"] = int(
            dom.get("terminal_kind") != "clarification"
            or dom.get("presentation_mode") is not None
            or dom.get("visible_product_ids") != []
            or dom.get("shelf_product_ids") != []
            or dom.get("legacy_message_count") != 0
            or dom.get("legacy_product_card_count") != 0
            or dom.get("turn_presentation_root_count") != 0
            or dom.get("clarification_message_count") != 1
            or bool(console)
            or bool(network)
        )
        return {
            "serious_failure_count": int(any(counters.values())),
            **counters,
        }
    telemetry = contract.get("telemetry")
    counters["copywriter_fallback_count"] = int(
        contract.get("copy_source") == "fallback"
        or (
            isinstance(telemetry, dict)
            and telemetry.get("fallback_reason") is not None
        )
    )
    stream_contracts = [
        payload
        for name, payload in events
        if name == "presentation_contract"
    ]
    event_names = tuple(name for name, _ in events)
    contract_ids = contract.get("visible_product_ids")
    dom_ids = dom.get("visible_product_ids")
    shelf_ids = dom.get("shelf_product_ids")
    product_payloads = [
        payload
        for name, payload in events
        if name == "products"
    ]
    products: list[Mapping[str, object]] = []
    if len(product_payloads) == 1:
        raw_products = product_payloads[0].get("products")
        if not isinstance(raw_products, list):
            raw_products = product_payloads[0].get("cards")
        if isinstance(raw_products, list):
            products = [
                item
                for item in raw_products
                if isinstance(item, dict)
            ]
    product_ids = [
        item.get("product_id", item.get("id"))
        for item in products
    ]
    counters["wrong_binding_count"] = int(
        not isinstance(contract_ids, list)
        or dom_ids != contract_ids
        or shelf_ids != contract_ids
        or product_ids != contract_ids
        or not _product_payloads_match_canonical(
            events=events,
            expected_product_ids=(
                contract_ids
                if isinstance(contract_ids, list)
                else ()
            ),
        )
    )
    counters["unaligned_price_specification_count"] = sum(
        1
        for item in products
        if (
            isinstance(item.get("specification"), str)
            and bool(str(item["specification"]).strip())
            and item.get("price_specification_alignment") != "aligned"
        )
    )
    counters["frontend_contract_violation_count"] = int(
        len(stream_contracts) != 1
        or stream_contracts[0] != contract
        or dom.get("presentation_mode") != contract.get("mode")
        or dom.get("legacy_message_count") != 0
        or dom.get("legacy_product_card_count") != 0
        or dom.get("turn_presentation_root_count") != 1
        or "message" in event_names
        or bool(console)
        or bool(network)
    )
    return {
        "serious_failure_count": int(any(counters.values())),
        **counters,
    }


def _capture_count(page) -> int:
    count = page.evaluate(
        "() => window.__mainlineAuditCaptures.length"
    )
    if not isinstance(count, int) or isinstance(count, bool):
        raise AuditBundleError("browser capture count is invalid")
    return count


def _wait_for_live_terminal(
    page,
    *,
    expected_capture_count: int,
) -> None:
    page.wait_for_function(
        """expected => (
            window.__mainlineAuditCaptures.length >= expected
            && window.__mainlineAuditCaptureErrors.length === 0
            && typeof activeChatRequests !== 'undefined'
            && activeChatRequests.size === 0
        )""",
        arg=expected_capture_count,
        timeout=120_000,
    )
    capture_errors = page.evaluate(
        "() => window.__mainlineAuditCaptureErrors"
    )
    if not isinstance(capture_errors, list) or capture_errors:
        raise AuditBundleError("browser SSE capture failed")
    if _capture_count(page) != expected_capture_count:
        raise AuditBundleError("browser SSE capture count is invalid")


def _write_live_turn_bundle(
    *,
    page,
    turn_dir: Path,
    trajectory_id: str,
    turn: BoundedBrowserTurn,
    viewport: str,
    capture_index: int,
    evidence: dict[str, list[dict[str, str]]],
) -> tuple[dict[str, Any], tuple[dict[str, Any], ...]]:
    capture = page.evaluate(
        """index => window.__mainlineAuditCaptures[index] || null""",
        capture_index,
    )
    if not isinstance(capture, dict):
        raise AuditBundleError("browser capture is unavailable")
    raw_bytes = capture.get("bytes")
    if (
        not isinstance(raw_bytes, list)
        or any(
            not isinstance(value, int)
            or isinstance(value, bool)
            or value < 0
            or value > 255
            for value in raw_bytes
        )
    ):
        raise AuditBundleError("browser capture bytes are invalid")
    events = capture.get("events")
    if not isinstance(events, list):
        raise AuditBundleError("browser capture events are invalid")
    request_id = page.evaluate(
        """() => {
            const wrappers = Array.from(document.querySelectorAll(
                '.message-wrapper.ai[data-guide-request-id]'
            ));
            return wrappers.at(-1)?.dataset.guideRequestId || null;
        }"""
    )
    if not isinstance(request_id, str) or not request_id:
        request_id = None
    request_body = capture.get("body")
    try:
        parsed_body = (
            json.loads(request_body)
            if isinstance(request_body, str)
            else None
        )
    except json.JSONDecodeError as error:
        raise AuditBundleError("browser request JSON is invalid") from error
    if not isinstance(parsed_body, dict):
        raise AuditBundleError("browser request body is unavailable")

    _write_json(
        turn_dir / "request.json",
        {
            "turn_id": f"{trajectory_id}-{turn.turn_id}",
            "request_id": request_id,
            "viewport": VIEWPORTS[viewport],
            "method": capture.get("method"),
            "url": capture.get("url"),
            "user_message": turn.message,
            "request_message": parsed_body.get("message"),
            "body": parsed_body,
        },
    )
    (turn_dir / "stream.sse").write_bytes(bytes(raw_bytes))
    try:
        terminal_kind, terminal = _terminal_from_capture_events(events)
    except AuditBundleError:
        _write_json(
            turn_dir / "presentation-contract.json",
            {"audit_error": "missing_presentation_contract"},
        )
        _write_json(
            turn_dir / "terminal-dom.json",
            _failed_terminal_dom(request_id),
        )
        _write_json(turn_dir / "console.json", evidence["console"])
        _write_json(turn_dir / "network.json", evidence["network"])
        page.screenshot(
            path=str(turn_dir / "screenshot.png"),
            full_page=True,
        )
        raise AuditBundleError(
            "browser capture must contain one typed terminal"
        )
    _write_json(turn_dir / "presentation-contract.json", terminal)
    if terminal_kind == "error":
        _write_json(
            turn_dir / "terminal-dom.json",
            _failed_terminal_dom(
                request_id,
                terminal_kind="error",
            ),
        )
        _write_json(turn_dir / "console.json", evidence["console"])
        _write_json(turn_dir / "network.json", evidence["network"])
        page.screenshot(
            path=str(turn_dir / "screenshot.png"),
            full_page=True,
        )
        error_data = terminal["error"]
        raise BoundedContractError(
            owner="sse_contract",
            failure_code=error_data["error"],
            message=error_data["error"],
        )
    if request_id is None:
        _write_json(
            turn_dir / "terminal-dom.json",
            _failed_terminal_dom(request_id),
        )
        _write_json(turn_dir / "console.json", evidence["console"])
        _write_json(turn_dir / "network.json", evidence["network"])
        page.screenshot(
            path=str(turn_dir / "screenshot.png"),
            full_page=True,
        )
        raise AuditBundleError("browser request ID is unavailable")
    _write_json(
        turn_dir / "terminal-dom.json",
        _terminal_dom(
            page,
            request_id=request_id,
            terminal_kind=terminal_kind,
        ),
    )
    _write_json(turn_dir / "console.json", evidence["console"])
    _write_json(turn_dir / "network.json", evidence["network"])
    page.screenshot(
        path=str(turn_dir / "screenshot.png"),
        full_page=True,
    )
    observations = tuple(
        event.get("data", {}).get("observation")
        for event in events
        if (
            isinstance(event, dict)
            and event.get("event") == "image_observation"
            and isinstance(event.get("data"), dict)
            and isinstance(
                event["data"].get("observation"),
                dict,
            )
        )
    )
    return terminal, observations


def _terminal_from_capture_events(
    events: list[object],
) -> tuple[str, dict[str, Any]]:
    presentations = tuple(
        event.get("data")
        for event in events
        if (
            isinstance(event, dict)
            and event.get("event") == "presentation_contract"
            and isinstance(event.get("data"), dict)
        )
    )
    clarifications = tuple(
        event.get("data")
        for event in events
        if (
            isinstance(event, dict)
            and event.get("event") == "clarify"
            and isinstance(event.get("data"), dict)
        )
    )
    errors = tuple(
        event.get("data")
        for event in events
        if (
            isinstance(event, dict)
            and event.get("event") == "error"
            and isinstance(event.get("data"), dict)
        )
    )
    if len(presentations) == 1 and not clarifications and not errors:
        return "presentation", presentations[0]
    if len(clarifications) == 1 and not presentations and not errors:
        clarification = clarifications[0]
        question = clarification.get("question")
        code = clarification.get("clarification_code")
        if (
            not isinstance(question, str)
            or not question
            or not isinstance(code, str)
            or not code
        ):
            raise AuditBundleError("clarification terminal is invalid")
        return (
            "clarification",
            {
                "terminal_kind": "clarification",
                "clarification": clarification,
            },
        )
    if len(errors) == 1 and not presentations and not clarifications:
        error = errors[0]
        code = error.get("error")
        message = error.get("message")
        if (
            not isinstance(code, str)
            or not code
            or (
                message is not None
                and not isinstance(message, str)
            )
        ):
            raise AuditBundleError("error terminal is invalid")
        return (
            "error",
            {
                "terminal_kind": "error",
                "error": error,
            },
        )
    raise AuditBundleError("browser capture must contain one typed terminal")


def _failed_terminal_dom(
    request_id: str | None,
    *,
    terminal_kind: str | None = None,
) -> dict[str, Any]:
    return {
        "request_id": request_id,
        "terminal_kind": terminal_kind,
        "presentation_mode": None,
        "legacy_message_count": 0,
        "legacy_product_card_count": 0,
        "turn_presentation_root_count": 0,
        "visible_section_kinds": [],
        "inline_product_ids": [],
        "visible_product_ids": [],
        "shelf_product_ids": [],
        "presentation_text": "",
    }


def _install_fixture_route(
    page,
    *,
    stream: bytes,
) -> None:
    events = _sse_events_from_sse(stream.decode("utf-8"))
    card_displays = tuple(
        payload
        for event_name, payload in events
        if event_name == "card_display_contract"
    )
    endings = tuple(
        payload
        for event_name, payload in events
        if event_name == "end"
    )
    clarifications = tuple(
        payload
        for event_name, payload in events
        if event_name == "clarify"
    )
    if (
        len(endings) != 1
        or (len(card_displays), len(clarifications))
        not in {(1, 0), (0, 1)}
    ):
        raise AuditBundleError(
            "fixture stream must contain one typed terminal"
        )
    feedback_target = (
        {
            "conversation_version": endings[0].get(
                "conversation_version"
            ),
            "displayed_product_ids": card_displays[0].get(
                "visible_product_ids"
            ),
            "profile_version": None,
        }
        if card_displays
        else None
    )

    def handle(route) -> None:
        request_url = route.request.url
        if not _is_loopback_host(urlsplit(request_url).hostname):
            route.abort("blockedbyclient")
            return
        request_path = urlsplit(request_url).path
        if request_path == "/api/v1/chat/stream":
            route.fulfill(
                status=200,
                content_type="text/event-stream; charset=utf-8",
                body=stream,
            )
            return
        if (
            request_path.startswith("/api/v1/chat/sessions/")
            and request_path.endswith("/feedback-target")
        ):
            if feedback_target is None:
                route.fulfill(
                    status=404,
                    content_type="application/json",
                    body=json.dumps({
                        "detail": {
                            "code": "FEEDBACK_TARGET_UNAVAILABLE",
                            "message": "该反馈目标不可用。",
                        }
                    }, ensure_ascii=False, separators=(",", ":")),
                )
                return
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(
                    feedback_target,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            )
            return
        route.continue_()

    page.route("http://**/*", handle)
    page.route("https://**/*", handle)


def _browser_evidence(page) -> dict[str, list[dict[str, str]]]:
    evidence: dict[str, list[dict[str, str]]] = {
        "console": [],
        "network": [],
        "requests": [],
    }
    page.on(
        "request",
        lambda request: evidence["requests"].append({
            "url": request.url,
            "method": request.method,
            "resource_type": request.resource_type,
        }),
    )
    page.on(
        "console",
        lambda message: evidence["console"].append({
            "type": message.type,
            "text": message.text,
        })
        if message.type == "error"
        else None,
    )
    page.on(
        "pageerror",
        lambda error: evidence["console"].append({
            "type": "pageerror",
            "text": str(error),
        }),
    )
    page.on(
        "requestfailed",
        lambda request: evidence["network"].append({
            "url": request.url,
            "error": str(request.failure),
        }),
    )
    return evidence


def _wait_for_fixture_terminal(page) -> None:
    page.wait_for_function(
        """() => {
            const captures = window.__mainlineAuditCaptures;
            const events = captures?.[0]?.events || [];
            const presentationCount = events.filter(
                item => item?.event === 'presentation_contract'
            ).length;
            const clarificationCount = events.filter(
                item => item?.event === 'clarify'
            ).length;
            const presentationRoots = document.querySelectorAll(
                '.message-wrapper.ai[data-guide-request-id] '
                + '.guide-presentation-root'
            ).length;
            const clarificationBubbles = Array.from(
                document.querySelectorAll(
                    '.message-wrapper.ai[data-guide-request-id]'
                )
            ).filter(wrapper => (
                !wrapper.querySelector('.guide-presentation-root')
                && wrapper.querySelector(':scope > .message-bubble')
                    ?.innerText.trim()
            )).length;
            return (
                captures.length === 1
                && window.__mainlineAuditCaptureErrors.length === 0
                && typeof activeChatRequests !== 'undefined'
                && activeChatRequests.size === 0
                && (
                    (
                        presentationCount === 1
                        && clarificationCount === 0
                        && presentationRoots === 1
                    )
                    || (
                        presentationCount === 0
                        && clarificationCount === 1
                        && presentationRoots === 0
                        && clarificationBubbles === 1
                    )
                )
            );
        }""",
        timeout=30_000,
    )


def _write_fixture_turn_bundle(
    *,
    page,
    turn_dir: Path,
    turn_id: str,
    viewport: str,
    evidence: dict[str, list[dict[str, str]]],
) -> None:
    capture = page.evaluate(
        "() => window.__mainlineAuditCaptures[0]"
    )
    if not isinstance(capture, dict):
        raise AuditBundleError("browser capture is unavailable")
    raw_bytes = capture.get("bytes")
    if (
        not isinstance(raw_bytes, list)
        or any(
            not isinstance(value, int)
            or value < 0
            or value > 255
            for value in raw_bytes
        )
    ):
        raise AuditBundleError("browser capture bytes are invalid")
    events = capture.get("events")
    if not isinstance(events, list):
        raise AuditBundleError("browser capture events are invalid")
    terminal_kind, terminal = _terminal_from_capture_events(events)
    if terminal_kind == "error":
        raise AuditBundleError(
            "fixture browser capture contains an error terminal"
        )
    request_id = page.evaluate(
        """() => document.querySelector(
            '.message-wrapper.ai[data-guide-request-id]'
        )?.dataset.guideRequestId || null"""
    )
    if not isinstance(request_id, str) or not request_id:
        raise AuditBundleError("browser request ID is unavailable")
    request_body = capture.get("body")
    try:
        parsed_body = (
            json.loads(request_body)
            if isinstance(request_body, str)
            else None
        )
    except json.JSONDecodeError as error:
        raise AuditBundleError("browser request JSON is invalid") from error
    _write_json(
        turn_dir / "request.json",
        {
            "turn_id": turn_id,
            "request_id": request_id,
            "viewport": VIEWPORTS[viewport],
            "method": capture.get("method"),
            "url": capture.get("url"),
            "body": parsed_body,
        },
    )
    (turn_dir / "stream.sse").write_bytes(bytes(raw_bytes))
    _write_json(
        turn_dir / "presentation-contract.json",
        terminal,
    )
    _write_json(
        turn_dir / "terminal-dom.json",
        _terminal_dom(
            page,
            request_id=request_id,
            terminal_kind=terminal_kind,
        ),
    )
    _write_json(turn_dir / "console.json", evidence["console"])
    _write_json(turn_dir / "network.json", evidence["network"])
    page.screenshot(
        path=str(turn_dir / "screenshot.png"),
        full_page=True,
    )


def _terminal_dom(
    page,
    *,
    request_id: str,
    terminal_kind: str,
) -> dict[str, Any]:
    dom = page.evaluate(
        """input => {
            const { requestId, terminalKind } = input;
            const wrapper = document.querySelector(
                `.message-wrapper.ai[data-guide-request-id="${requestId}"]`
            );
            if (!wrapper) return null;
            const roots = Array.from(
                wrapper.querySelectorAll('.guide-presentation-root')
            );
            const root = roots[0] || null;
            const productIds = selector => (
                root
                    ? Array.from(root.querySelectorAll(selector))
                        .map(node => Number(node.dataset.guideProductId))
                        .filter(Number.isInteger)
                    : []
            );
            const inlineProductIds = productIds(
                '[data-guide-card-form="inline"]'
            );
            const shelfProductIds = productIds(
                '[data-guide-card-form="shelf"]'
            );
            const clarification = terminalKind === 'clarification';
            const legacyBubbles = clarification
                ? []
                : Array.from(
                    wrapper.querySelectorAll('.message-bubble')
                ).filter(bubble => !bubble.querySelector(
                    ':scope > .guide-presentation-root'
                ));
            return {
                request_id: requestId,
                terminal_kind: terminalKind,
                presentation_mode: root?.dataset.presentationMode || null,
                legacy_message_count: legacyBubbles.length,
                clarification_message_count: clarification
                    ? wrapper.querySelectorAll(
                        ':scope > .message-bubble'
                    ).length
                    : 0,
                legacy_product_card_count: root
                    ? root.querySelectorAll(
                        '.recommendation-card:not([data-guide-card-form])'
                    ).length
                    : 0,
                turn_presentation_root_count: roots.length,
                comparison_table_count: root
                    ? root.querySelectorAll(
                        '[data-guide-comparison-table="true"]'
                    ).length
                    : 0,
                visible_section_kinds: root
                    ? Array.from(
                        root.querySelectorAll('[data-section-kind]')
                    ).map(node => node.dataset.sectionKind)
                    : [],
                section_blocks: root
                    ? Array.from(
                        root.querySelectorAll('[data-section-kind]')
                    ).map(node => ({
                        kind: node.dataset.sectionKind,
                        text: node.innerText || ''
                    }))
                    : [],
                inline_product_ids: inlineProductIds,
                visible_product_ids: Array.from(
                    new Set([...inlineProductIds, ...shelfProductIds])
                ),
                shelf_product_ids: shelfProductIds,
                presentation_text: clarification
                    ? wrapper.innerText
                    : root?.innerText || '',
            };
        }""",
        {
            "requestId": request_id,
            "terminalKind": terminal_kind,
        },
    )
    if not isinstance(dom, dict):
        raise AuditBundleError("terminal DOM is unavailable")
    return dom


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _write_bytes_exclusive(
    path: Path,
    content: bytes,
    *,
    label: str,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as stream:
            stream.write(content)
    except FileExistsError as exc:
        raise AuditBundleError(
            f"{label} already exists: {path}"
        ) from exc


def _write_json_exclusive(
    path: Path,
    payload: object,
    *,
    label: str,
) -> None:
    _write_bytes_exclusive(
        path,
        _canonical_bytes(payload),
        label=label,
    )


def _artifact_sha256_by_path(
    root: Path,
    *,
    excluded: set[Path],
) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): sha256(
            path.read_bytes()
        ).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file() and path not in excluded
    }


def _finalize_fixture_sandbox_evidence(
    *,
    base_url: str,
    output: Path,
    child_report: dict[str, Any],
    sandbox_profile: str,
    measurement_nonce: str,
    seatbelt_raw: bytes,
    logger_stderr: bytes,
    logger_returncode: int,
    sandbox_root_pid: int,
    sandbox_process_group_id: int,
    process_group_quiescent: bool,
) -> dict[str, Any]:
    summary_path = output / "summary.json"
    if summary_path.exists() or summary_path.is_symlink():
        raise AuditBundleError(
            f"fixture browser summary already exists: {summary_path}"
        )
    browser_requests = child_report.get("browser_requests")
    reported_sandbox_root_pid = child_report.get("sandbox_root_pid")
    turns = child_report.get("turns")
    if (
        not isinstance(browser_requests, list)
        or any(not isinstance(item, dict) for item in browser_requests)
        or type(reported_sandbox_root_pid) is not int
        or reported_sandbox_root_pid != sandbox_root_pid
        or sandbox_process_group_id != sandbox_root_pid
        or process_group_quiescent is not True
        or not isinstance(turns, list)
        or any(
            not isinstance(turn, dict)
            or not isinstance(turn.get("directory"), str)
            for turn in turns
        )
    ):
        raise AuditBundleError(
            "fixture sandbox child report is invalid"
        )
    raw_path = output / "seatbelt.raw.ndjson"
    audit_path = output / "sandbox-audit.json"
    requests_path = output / "browser-requests.json"
    _write_bytes_exclusive(
        raw_path,
        seatbelt_raw,
        label="fixture Seatbelt raw audit",
    )
    _write_json_exclusive(
        requests_path,
        browser_requests,
        label="fixture browser requests",
    )
    try:
        audit = _build_fixture_sandbox_audit(
            base_url=base_url,
            browser_requests=browser_requests,
            netlog_path=output / "chromium-netlog.json",
            sandbox_profile=sandbox_profile,
            measurement_nonce=measurement_nonce,
            seatbelt_raw=seatbelt_raw,
            logger_stderr=logger_stderr,
            logger_returncode=logger_returncode,
            sandbox_process_group_id=sandbox_process_group_id,
            process_group_quiescent=process_group_quiescent,
        )
        if audit["root_pid"] != reported_sandbox_root_pid:
            raise AuditBundleError(
                "fixture sandbox root PID does not match child report"
            )
    except AuditBundleError as exc:
        failure_code = (
            "non_loopback_attempt"
            if "non-loopback" in str(exc)
            else "seatbelt_evidence_invalid"
        )
        failed_audit = {
            "schema_version": "guide-fixture-browser-sandbox-audit-v2",
            "passed": False,
            "failure_code": failure_code,
            "failure": str(exc),
            "measurement": "macos-unified-log-seatbelt-kernel",
            "measurement_nonce": measurement_nonce,
            "sandbox_profile_sha256": sha256(
                sandbox_profile.encode("utf-8")
            ).hexdigest(),
            "seatbelt_raw_ndjson_sha256": sha256(
                seatbelt_raw
            ).hexdigest(),
            "seatbelt_raw_byte_count": len(seatbelt_raw),
            "logger_returncode": logger_returncode,
        }
        _write_json_exclusive(
            audit_path,
            failed_audit,
            label="fixture sandbox audit",
        )
        audit_bytes = audit_path.read_bytes()
        for turn in turns:
            _write_bytes_exclusive(
                output / turn["directory"] / "sandbox-audit.json",
                audit_bytes,
                label="fixture turn sandbox audit",
            )
        failed_report = {
            key: value
            for key, value in child_report.items()
            if key not in {"browser_requests", "sandbox_root_pid"}
        }
        failed_report.update({
            "passed": False,
            "sandbox_audit_sha256": sha256(audit_bytes).hexdigest(),
            "seatbelt_raw_ndjson_sha256": failed_audit[
                "seatbelt_raw_ndjson_sha256"
            ],
            "process_tree_non_loopback_attempt_count": (
                1 if failure_code == "non_loopback_attempt" else None
            ),
        })
        failed_report["artifact_sha256_by_path"] = (
            _artifact_sha256_by_path(
                output,
                excluded={summary_path},
            )
        )
        _write_json_exclusive(
            summary_path,
            failed_report,
            label="fixture browser summary",
        )
        raise
    _write_json_exclusive(
        audit_path,
        audit,
        label="fixture sandbox audit",
    )
    audit_bytes = audit_path.read_bytes()
    for turn in turns:
        _write_bytes_exclusive(
            output / turn["directory"] / "sandbox-audit.json",
            audit_bytes,
            label="fixture turn sandbox audit",
        )
    report = {
        key: value
        for key, value in child_report.items()
        if key not in {"browser_requests", "sandbox_root_pid"}
    }
    report.update({
        "passed": (
            child_report.get("passed") is True
            and audit.get("passed") is True
        ),
        "sandbox_identity": audit["sandbox_identity"],
        "sandbox_audit_sha256": sha256(audit_bytes).hexdigest(),
        "seatbelt_raw_ndjson_sha256": audit[
            "seatbelt_raw_ndjson_sha256"
        ],
        "browser_request_count": audit["browser_request_count"],
        "process_tree_non_loopback_attempt_count": audit[
            "process_tree_non_loopback_attempt_count"
        ],
        "browser_observed_non_loopback_attempt_count": audit[
            "browser_observed_non_loopback_attempt_count"
        ],
    })
    report["artifact_sha256_by_path"] = _artifact_sha256_by_path(
        output,
        excluded={output / "summary.json"},
    )
    _write_json_exclusive(
        summary_path,
        report,
        label="fixture browser summary",
    )
    return report


def _publish_fixture_sandbox_failure(
    *,
    output: Path,
    sandbox_profile: str,
    measurement_nonce: str,
    seatbelt_raw: bytes,
    logger_stderr: bytes,
    logger_returncode: int,
    child_returncode: int,
    child_stderr: bytes,
) -> dict[str, object]:
    if not output.exists():
        output.mkdir(parents=True, exist_ok=False)
    if not output.is_dir() or output.is_symlink():
        raise AuditBundleError(
            "fixture browser failure output is invalid"
        )
    profile_path = output / "sandbox-profile.sb"
    profile_bytes = sandbox_profile.encode("utf-8")
    if profile_path.exists():
        if (
            profile_path.is_symlink()
            or profile_path.read_bytes() != profile_bytes
        ):
            raise AuditBundleError(
                "fixture sandbox profile artifact is invalid"
            )
    else:
        _write_bytes_exclusive(
            profile_path,
            profile_bytes,
            label="fixture sandbox profile",
        )
    raw_path = output / "seatbelt.raw.ndjson"
    _write_bytes_exclusive(
        raw_path,
        seatbelt_raw,
        label="fixture Seatbelt raw audit",
    )
    audit = {
        "schema_version": "guide-fixture-browser-sandbox-audit-v2",
        "passed": False,
        "failure_code": "sandbox_child_failed",
        "measurement": "macos-unified-log-seatbelt-kernel",
        "measurement_nonce": measurement_nonce,
        "sandbox_profile_sha256": sha256(profile_bytes).hexdigest(),
        "seatbelt_raw_ndjson_sha256": sha256(
            seatbelt_raw
        ).hexdigest(),
        "seatbelt_raw_byte_count": len(seatbelt_raw),
        "logger_returncode": logger_returncode,
        "logger_stderr_sha256": sha256(logger_stderr).hexdigest(),
        "child_returncode": child_returncode,
        "child_stderr_sha256": sha256(child_stderr).hexdigest(),
    }
    audit_path = output / "sandbox-audit.json"
    _write_json_exclusive(
        audit_path,
        audit,
        label="fixture sandbox audit",
    )
    audit_bytes = audit_path.read_bytes()
    for turn_id in FIXTURE_TURN_IDS:
        turn_dir = output / turn_id
        if turn_dir.is_dir():
            _write_bytes_exclusive(
                turn_dir / "sandbox-audit.json",
                audit_bytes,
                label="fixture turn sandbox audit",
            )
    report: dict[str, object] = {
        "schema_version": "guide-mainline-contract-browser-audit-v1",
        "trajectory_set": "fixture",
        "passed": False,
        "failure_code": "sandbox_child_failed",
        "sandbox_audit_sha256": sha256(audit_bytes).hexdigest(),
        "seatbelt_raw_ndjson_sha256": audit[
            "seatbelt_raw_ndjson_sha256"
        ],
        "child_returncode": child_returncode,
    }
    summary_path = output / "summary.json"
    report["artifact_sha256_by_path"] = _artifact_sha256_by_path(
        output,
        excluded={summary_path},
    )
    _write_json_exclusive(
        summary_path,
        report,
        label="fixture browser summary",
    )
    return report


def validate_audit_bundle(
    turn_dir: Path,
    *,
    expected_turn_id: str,
) -> None:
    if not turn_dir.is_dir():
        raise AuditBundleError("audit turn directory is missing")
    missing = REQUIRED_TURN_FILES - {
        path.name for path in turn_dir.iterdir()
    }
    if missing:
        raise AuditBundleError(
            "missing audit files: " + ", ".join(sorted(missing))
        )

    request = _read_object(turn_dir / "request.json")
    if request.get("turn_id") != expected_turn_id:
        raise AuditBundleError("request turn ID mismatch")
    request_id = request.get("request_id")
    if not isinstance(request_id, str) or not request_id:
        raise AuditBundleError("request ID is missing")
    _validate_screenshot_png(
        turn_dir / "screenshot.png",
        request=request,
    )

    contract = _read_object(
        turn_dir / "presentation-contract.json"
    )
    dom = _read_object(turn_dir / "terminal-dom.json")
    if dom.get("request_id") != request_id:
        raise AuditBundleError("DOM request ID mismatch")
    raw_stream = (turn_dir / "stream.sse").read_text(
        encoding="utf-8"
    )
    stream_events = _sse_events_from_sse(raw_stream)
    _validate_success_stream_lifecycle(stream_events)
    _validate_stream_terminal_ownership(
        stream_events,
        clarification=(
            contract.get("terminal_kind") == "clarification"
        ),
    )
    if contract.get("terminal_kind") == "clarification":
        _validate_clarification_bundle(
            terminal=contract,
            dom=dom,
            stream_events=stream_events,
        )
        if _read_list(turn_dir / "console.json"):
            raise AuditBundleError("browser console is not empty")
        if _read_list(turn_dir / "network.json"):
            raise AuditBundleError(
                "browser network failures are not empty"
            )
        return
    if dom.get("presentation_mode") != contract.get("mode"):
        raise AuditBundleError("DOM contract mode mismatch")

    sections = tuple(
        contract["sections"]
        if isinstance(contract.get("sections"), list)
        else ()
    )
    expected_section_kinds = [
        section["kind"]
        for section in sections
        if (
            isinstance(section, dict)
            and isinstance(section.get("kind"), str)
        )
    ]
    if dom.get("visible_section_kinds") != expected_section_kinds:
        raise AuditBundleError("DOM section order mismatch")
    _validate_section_blocks(
        sections=sections,
        section_blocks=dom.get("section_blocks"),
    )
    expected_inline_product_ids = [
        section["product_id"]
        for section in sections
        if (
            isinstance(section, dict)
            and section.get("kind") == "product"
            and isinstance(section.get("product_id"), int)
        )
    ]
    if dom.get("inline_product_ids") != expected_inline_product_ids:
        raise AuditBundleError("DOM inline product IDs mismatch")
    visible_product_ids = contract.get("visible_product_ids")
    if not isinstance(visible_product_ids, list):
        raise AuditBundleError("contract visible product IDs are invalid")
    if dom.get("visible_product_ids") != visible_product_ids:
        raise AuditBundleError("DOM visible product IDs mismatch")
    if dom.get("shelf_product_ids") != visible_product_ids:
        raise AuditBundleError("DOM shelf product IDs mismatch")
    if not _product_payloads_match_canonical(
        events=stream_events,
        expected_product_ids=visible_product_ids,
    ):
        raise AuditBundleError("canonical product binding mismatch")
    if dom.get("legacy_message_count") != 0:
        raise AuditBundleError("legacy message rendered")
    if dom.get("legacy_product_card_count") != 0:
        raise AuditBundleError("legacy product card rendered")
    if dom.get("turn_presentation_root_count") != 1:
        raise AuditBundleError("presentation root count mismatch")
    if (
        contract.get("mode") == "comparison"
        and dom.get("comparison_table_count") != 1
    ):
        raise AuditBundleError("comparison table count mismatch")

    presentation_text = dom.get("presentation_text")
    if not isinstance(presentation_text, str):
        raise AuditBundleError("DOM presentation text is invalid")
    normalized_presentation_text = _normalize_visible_text(
        presentation_text
    )
    missing_text = tuple(
        text
        for text in required_public_text(sections)
        if _normalize_visible_text(text)
        not in normalized_presentation_text
    )
    if missing_text:
        raise AuditBundleError("DOM presentation text mismatch")

    stream_contracts = tuple(
        data
        for event, data in stream_events
        if event == "presentation_contract"
    )
    if len(stream_contracts) != 1:
        raise AuditBundleError(
            "stream must contain one presentation contract"
        )
    if stream_contracts[0] != contract:
        raise AuditBundleError("stream presentation contract mismatch")
    if _read_list(turn_dir / "console.json"):
        raise AuditBundleError("browser console is not empty")
    if _read_list(turn_dir / "network.json"):
        raise AuditBundleError("browser network failures are not empty")


def _validate_demo_usefulness(
    *,
    contract: Mapping[str, object],
    events: Sequence[tuple[str, Mapping[str, object]]],
) -> None:
    del events
    if contract.get("terminal_kind") == "clarification":
        return
    responsibility = contract.get("responsibility")
    mode = contract.get("mode")
    sections = contract.get("sections")
    if not isinstance(sections, list):
        raise AuditBundleError("presentation sections are invalid")

    if responsibility == "comparison" or mode == "comparison":
        rows = contract.get("comparison_rows")
        if not isinstance(rows, list):
            raise AuditBundleError("comparison rows are invalid")
        useful_rows = [
            row
            for row in rows
            if isinstance(row, dict)
            and isinstance(row.get("cells"), list)
            and bool(row["cells"])
            and all(
                isinstance(cell, dict)
                and cell.get("state") == "known"
                and isinstance(cell.get("fact_ids"), list)
                and bool(cell["fact_ids"])
                and isinstance(cell.get("value"), str)
                and bool(cell["value"].strip())
                for cell in row["cells"]
            )
        ]
        requested = contract.get("requested_comparison_dimensions")
        if not isinstance(requested, list):
            raise AuditBundleError(
                "requested comparison dimensions are invalid"
            )
        if not requested and len(useful_rows) < 2:
            raise AuditBundleError(
                "comparison has no useful dimensions"
            )
        return

    if responsibility == "recommendation":
        visible_product_ids = contract.get("visible_product_ids")
        if not isinstance(visible_product_ids, list):
            raise AuditBundleError(
                "recommendation visible products are invalid"
            )
        product_sections = {
            section.get("product_id"): section
            for section in sections
            if (
                isinstance(section, dict)
                and section.get("kind") == "product"
                and isinstance(section.get("product_id"), int)
            )
        }
        for product_id in visible_product_ids:
            section = product_sections.get(product_id)
            if section is None or not _section_has_fact_support(section):
                raise AuditBundleError(
                    "recommendation product has no fact-backed reason"
                )
        return

    if responsibility == "product_knowledge" or mode == "product_knowledge":
        answer = next(
            (
                section
                for section in sections
                if (
                    isinstance(section, dict)
                    and section.get("kind") == "answer"
                )
            ),
            None,
        )
        if (
            answer is None
            or not isinstance(answer.get("copy_text"), str)
            or not answer["copy_text"].strip()
        ):
            raise AuditBundleError(
                "product knowledge answer is empty"
            )
        answer_text = answer["copy_text"]
        evidence_gap_markers = (
            "尚未确认",
            "暂无",
            "缺少",
            "没有明确",
            "没有足够",
            "无法确认",
        )
        if (
            not _section_has_fact_support(answer)
            and not any(
                marker in answer_text
                for marker in evidence_gap_markers
            )
        ):
            raise AuditBundleError(
                "product knowledge answer is not evidence-backed"
            )


def _section_has_fact_support(
    section: Mapping[str, object],
) -> bool:
    for key in ("used_fact_ids", "advisor_used_fact_ids"):
        values = section.get(key)
        if isinstance(values, list) and values:
            return True
    direct_facts = section.get("direct_facts")
    return (
        isinstance(direct_facts, list)
        and any(
            isinstance(item, dict)
            and isinstance(item.get("fact_id"), str)
            and bool(item["fact_id"])
            for item in direct_facts
        )
    )


def _validate_section_blocks(
    *,
    sections: tuple[object, ...],
    section_blocks: object,
) -> None:
    if not isinstance(section_blocks, list):
        raise AuditBundleError("DOM section blocks are missing")
    if len(section_blocks) != len(sections):
        raise AuditBundleError("DOM section block count mismatch")
    for section, block in zip(sections, section_blocks, strict=True):
        if not isinstance(section, dict) or not isinstance(block, dict):
            raise AuditBundleError("DOM section block is invalid")
        if block.get("kind") != section.get("kind"):
            raise AuditBundleError("DOM section block order mismatch")
        block_text = block.get("text")
        if not isinstance(block_text, str):
            raise AuditBundleError("DOM section block text is invalid")
        normalized_block = _normalize_visible_text(block_text)
        required = tuple(
            _normalize_visible_text(text)
            for text in _required_section_text(section)
        )
        cursor = 0
        for text in required:
            position = normalized_block.find(text, cursor)
            if position < 0:
                raise AuditBundleError("DOM section text mismatch")
            cursor = position + len(text)


def _required_section_text(
    section: dict[str, Any],
) -> tuple[str, ...]:
    direct_facts = section.get("direct_facts", ())
    return tuple(
        text
        for text in (
            section.get("copy_text"),
            *(
                item.get("display_value")
                for item in direct_facts
                if isinstance(item, dict)
            ),
            section.get("advisor_reason"),
        )
        if isinstance(text, str) and text
    )


def _validate_clarification_bundle(
    *,
    terminal: dict[str, Any],
    dom: dict[str, Any],
    stream_events: tuple[tuple[str, dict[str, Any]], ...],
) -> None:
    clarification = terminal.get("clarification")
    if not isinstance(clarification, dict):
        raise AuditBundleError("clarification terminal is invalid")
    question = clarification.get("question")
    code = clarification.get("clarification_code")
    if (
        not isinstance(question, str)
        or not question
        or not isinstance(code, str)
        or not code
    ):
        raise AuditBundleError("clarification terminal is invalid")
    if (
        dom.get("terminal_kind") != "clarification"
        or dom.get("presentation_mode") is not None
        or dom.get("legacy_message_count") != 0
        or dom.get("clarification_message_count") != 1
        or dom.get("legacy_product_card_count") != 0
        or dom.get("turn_presentation_root_count") != 0
        or dom.get("visible_section_kinds") != []
        or dom.get("inline_product_ids") != []
        or dom.get("visible_product_ids") != []
        or dom.get("shelf_product_ids") != []
    ):
        raise AuditBundleError("clarification DOM shape mismatch")
    presentation_text = dom.get("presentation_text")
    if (
        not isinstance(presentation_text, str)
        or question not in presentation_text
    ):
        raise AuditBundleError("clarification DOM text mismatch")
    event_names = tuple(event for event, _ in stream_events)
    clarification_events = tuple(
        data
        for event, data in stream_events
        if event == "clarify"
    )
    intent_events = tuple(
        data
        for event, data in stream_events
        if event == "intent"
    )
    if (
        event_names.count("presentation_contract") != 0
        or event_names.count("clarify") != 1
        or event_names.count("end") != 1
        or "error" in event_names
        or "message" in event_names
        or len(intent_events) != 1
        or not isinstance(intent_events[0].get("intent"), str)
        or not intent_events[0]["intent"].strip()
        or clarification_events[0] != clarification
    ):
        raise AuditBundleError("clarification stream mismatch")


def _sse_events_from_sse(
    raw: str,
) -> tuple[tuple[str, dict[str, Any]], ...]:
    events: list[tuple[str, dict[str, Any]]] = []
    for block in raw.replace("\r\n", "\n").split("\n\n"):
        if not block.strip():
            continue
        event_name = None
        data_lines: list[str] = []
        for line in block.splitlines():
            if line.startswith("event:"):
                if event_name is not None:
                    raise AuditBundleError(
                        "stream event has duplicate event fields"
                    )
                event_name = line.removeprefix("event:").strip()
            elif line.startswith("data:"):
                data_lines.append(line.removeprefix("data:").lstrip())
            elif line.strip():
                raise AuditBundleError(
                    "stream event contains an unsupported field"
                )
        if event_name is None or not data_lines:
            raise AuditBundleError("stream event is incomplete")
        try:
            payload = json.loads("\n".join(data_lines))
        except json.JSONDecodeError as exc:
            raise AuditBundleError(
                "stream event is invalid JSON"
            ) from exc
        if not isinstance(payload, dict):
            raise AuditBundleError(
                "stream event must be an object"
            )
        events.append((event_name, payload))
    return tuple(events)


def _validate_success_stream_lifecycle(
    events: tuple[tuple[str, dict[str, Any]], ...],
) -> None:
    names = tuple(name for name, _ in events)
    if (
        names.count("start") != 1
        or names.count("end") != 1
        or names.count("error") != 0
        or not names
        or names[0] != "start"
        or names[-1] != "end"
    ):
        raise AuditBundleError("stream lifecycle is invalid")


def _validate_stream_terminal_ownership(
    events: tuple[tuple[str, dict[str, Any]], ...],
    *,
    clarification: bool,
) -> None:
    names = tuple(name for name, _ in events)
    if (
        names.count("presentation_contract")
        != (0 if clarification else 1)
        or names.count("clarify") != (1 if clarification else 0)
        or names.count("message") != 0
    ):
        raise AuditBundleError("stream terminal ownership is invalid")


def _read_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AuditBundleError(f"invalid audit file: {path.name}") from exc
    if not isinstance(payload, dict):
        raise AuditBundleError(f"audit file must be object: {path.name}")
    return payload


def _read_list(path: Path) -> list[Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AuditBundleError(f"invalid audit file: {path.name}") from exc
    if not isinstance(payload, list):
        raise AuditBundleError(f"audit file must be list: {path.name}")
    return payload


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--runtime-identity", type=Path)
    parser.add_argument(
        "--expected-manifest-sha256",
    )
    parser.add_argument(
        "--trajectory-set",
        choices=("fixture", "bounded", "release", "demo"),
        required=True,
    )
    parser.add_argument(
        "--viewport",
        choices=("desktop", "mobile", "all"),
        required=True,
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--attempt-context", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments[:1] == ["--seatbelt-canary-child"]:
        if len(arguments) != 4:
            raise SystemExit("seatbelt canary child arguments are invalid")
        try:
            port = int(arguments[3])
        except ValueError as exc:
            raise SystemExit(
                "seatbelt canary child port is invalid"
            ) from exc
        if arguments[2] == "drain":
            _require_fixture_canary_gate(b"1", stage="drain")
        return _run_seatbelt_canary_child(
            arguments[1],
            arguments[2],
            port,
        )
    if arguments[:1] == ["--seatbelt-canary-branch"]:
        if len(arguments) != 2:
            raise SystemExit("seatbelt canary branch arguments are invalid")
        return _run_seatbelt_canary_branch(arguments[1])
    args = _parser().parse_args(arguments)
    output = resolve_cli_output(
        trajectory_set=args.trajectory_set,
        output=args.output,
        attempt_context=args.attempt_context,
    )
    if (
        args.trajectory_set in {"fixture", "bounded", "release"}
        and args.expected_manifest_sha256 is None
    ):
        raise SystemExit(
            f"{args.trajectory_set} requires "
            "--expected-manifest-sha256"
        )
    if args.trajectory_set == "fixture":
        if args.runtime_identity is None:
            raise SystemExit("fixture requires --runtime-identity")
        sandbox_context = _fixture_sandbox_context()
        if sandbox_context is None:
            return _run_fixture_in_macos_sandbox(
                arguments,
                output=output,
            )
        _require_fixture_canary_gate(b"1", stage="start")
        sandbox_root_pid = _run_seatbelt_canaries(
            sandbox_context["measurement_nonce"]
        )
        _require_fixture_canary_gate(b"2", stage="completion")
        runtime_proof = _verified_fixture_runtime(
            base_url=args.base_url,
            runtime_identity_path=args.runtime_identity,
            expected_manifest_sha256=(
                args.expected_manifest_sha256
            ),
        )
        report = run_fixture_browser_audits(
            base_url=args.base_url,
            output=output,
            viewport=args.viewport,
            runtime_proof=runtime_proof,
            sandbox_profile=sandbox_context["sandbox_profile"],
            sandbox_root_pid=sandbox_root_pid,
        )
    elif args.trajectory_set == "bounded":
        report = run_authorized_bounded_browser_audit(
            base_url=args.base_url,
            attempt_context=output,
            viewport=args.viewport,
            expected_manifest_sha256=(
                args.expected_manifest_sha256
            ),
        )
    elif args.trajectory_set == "release":
        report = run_authorized_release_browser_audit(
            base_url=args.base_url,
            attempt_context=output,
            viewport=args.viewport,
            expected_manifest_sha256=(
                args.expected_manifest_sha256
            ),
        )
    else:
        report = run_bounded_browser_audit(
            base_url=args.base_url,
            output=output,
            viewport=args.viewport,
            trajectories=DEMO_TRAJECTORIES,
            trajectory_set="demo",
        )
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "AuditBundleError",
    "BOUNDED_TRAJECTORIES",
    "DEMO_TRAJECTORIES",
    "FIXTURE_TURN_IDS",
    "RELEASE_TRAJECTORIES",
    "REQUIRED_TURN_FILES",
    "derive_release_turn_counters",
    "fixture_sse_bytes",
    "required_public_text",
    "resolve_cli_output",
    "run_authorized_bounded_browser_audit",
    "run_bounded_browser_audit",
    "run_fixture_browser_audit",
    "run_fixture_browser_audits",
    "run_authorized_release_browser_audit",
    "run_release_browser_audit",
    "shutdown_zero_api_runtime",
    "validate_bounded_contract",
    "validate_completed_bounded_browser_evidence",
    "validate_completed_release_browser_evidence",
    "validate_audit_bundle",
]
