from __future__ import annotations

import base64
import inspect
import json
from functools import lru_cache
from hashlib import sha256
from pathlib import Path
import threading
import struct
import zlib

import pytest

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
)

from app.guide.application import public_event_envelope
from tools.guide_gates import (
    frontend_presentation_browser_audit as frontend_browser_audit,
)
import tools.guide_gates.run_mainline_contract_browser_audit as mainline_audit
from tools.guide_gates.run_mainline_contract_browser_audit import (
    AuditBundleError,
    FIXTURE_TURN_IDS,
    REQUIRED_TURN_FILES,
    fixture_sse_bytes,
    required_public_text,
    validate_audit_bundle,
)


ROOT = Path(__file__).resolve().parents[3]
TEST_RUNTIME_PRIVATE_KEY = Ed25519PrivateKey.from_private_bytes(
    bytes(range(32))
)
TEST_RUNTIME_PUBLIC_KEY = (
    base64.urlsafe_b64encode(
        TEST_RUNTIME_PRIVATE_KEY.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
    )
    .decode("ascii")
    .rstrip("=")
)
CHALLENGE_SIGNATURE_DOMAIN = (
    b"xiaoro-guide-zero-api-runtime-challenge-v1\x00"
)


def _signed_challenge(unsigned: dict[str, str]) -> dict[str, str]:
    signed = {
        **unsigned,
        "challenge_sha256": sha256(
            mainline_audit._canonical_bytes(unsigned)
        ).hexdigest(),
    }
    return {
        **signed,
        "challenge_signature": (
            base64.urlsafe_b64encode(
                TEST_RUNTIME_PRIVATE_KEY.sign(
                    CHALLENGE_SIGNATURE_DOMAIN
                    + mainline_audit._canonical_bytes(signed)
                )
            )
            .decode("ascii")
            .rstrip("=")
        ),
    }


def _paeth_predictor(left: int, above: int, upper_left: int) -> int:
    estimate = left + above - upper_left
    left_distance = abs(estimate - left)
    above_distance = abs(estimate - above)
    upper_left_distance = abs(estimate - upper_left)
    if left_distance <= above_distance and left_distance <= upper_left_distance:
        return left
    if above_distance <= upper_left_distance:
        return above
    return upper_left


@lru_cache(maxsize=16)
def _png_bytes(
    width: int,
    height: int,
    *,
    solid_color: tuple[int, int, int] | None = None,
    nearly_blank: bool = False,
) -> bytes:
    def chunk(kind: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + kind
            + payload
            + struct.pack(
                ">I",
                zlib.crc32(kind + payload) & 0xFFFFFFFF,
            )
        )

    def row_pixels(row_index: int) -> bytes:
        row = bytearray()
        for column in range(width):
            if solid_color is not None:
                color = solid_color
            elif nearly_blank:
                color = (
                    (32, 96, 192)
                    if row_index == 0 and column == 0
                    else (255, 255, 255)
                )
            else:
                x_band = min(7, column * 8 // width)
                y_band = min(7, row_index * 8 // height)
                color = (
                    (31 * x_band + 17 * y_band) % 256,
                    (47 * x_band + 29 * y_band + 40) % 256,
                    (13 * x_band + 61 * y_band + 80) % 256,
                )
            row.extend(color)
        return bytes(row)

    encoded = bytearray()
    previous = bytes(width * 3)
    for row_index in range(height):
        current = row_pixels(row_index)
        filter_type = row_index % 5
        filtered = bytearray(len(current))
        for index, value in enumerate(current):
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
                else _paeth_predictor(left, above, upper_left)
            )
            filtered[index] = (value - predictor) & 0xFF
        encoded.append(filter_type)
        encoded.extend(filtered)
        previous = current
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(
            b"IHDR",
            struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0),
        )
        + chunk(b"IDAT", zlib.compress(bytes(encoded)))
        + chunk(b"IEND", b"")
    )


def _write_bundle_payloads(
    directory: Path,
    payloads: dict[str, object],
) -> None:
    for name, content in payloads.items():
        path = directory / name
        if name == "screenshot.png":
            if not isinstance(content, bytes):
                raise AssertionError("test screenshot must be PNG bytes")
            path.write_bytes(content)
        else:
            if not isinstance(content, str):
                raise AssertionError("test payload must be text")
            path.write_text(content, encoding="utf-8")


def _presentation_stream(
    contract: dict[str, object],
    *,
    product_ids: tuple[int, ...] = (),
) -> str:
    products_event = ""
    if product_ids:
        fixture_turn = (
            "fixture-product-knowledge"
            if product_ids == (38,)
            else "fixture-comparison"
        )
        products = next(
            payload
            for event, payload in mainline_audit._sse_events_from_sse(
                fixture_sse_bytes(fixture_turn).decode("utf-8")
            )
            if event == "products"
        )
        products_event = (
            "event: products\n"
            f"data: {json.dumps(products, ensure_ascii=False)}\n\n"
        )
    return (
        "event: start\n"
        "data: {\"session_id\":\"audit-test\"}\n\n"
        f"{products_event}"
        "event: presentation_contract\n"
        f"data: {json.dumps(contract)}\n\n"
        "event: end\n"
        "data: {\"conversation_version\":1}\n\n"
    )


def _mutate_product_payload(
    raw: bytes,
    *,
    field_name: str,
    forged_value: object,
    groups: tuple[str, ...],
) -> bytes:
    events = mainline_audit._sse_events_from_sse(
        raw.decode("utf-8")
    )
    rewritten: list[tuple[str, dict[str, object]]] = []
    for event_name, payload in events:
        current = json.loads(json.dumps(payload))
        if event_name == "products":
            for group in groups:
                for item in current[group]:
                    item[field_name] = forged_value
        rewritten.append((event_name, current))
    return b"".join(
        (
            f"event: {event_name}\n"
            "data: "
            f"{json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}"
            "\n\n"
        ).encode("utf-8")
        for event_name, payload in rewritten
    )


def _write_minimal_presentation_bundle(
    turn_dir: Path,
    *,
    stream: str | None = None,
) -> None:
    request = {
        "turn_id": "terminal-sequence-001",
        "request_id": "request-terminal-sequence-001",
    }
    contract = {
        "mode": "general_knowledge",
        "visible_product_ids": [],
        "sections": [
            {"kind": "answer", "copy_text": "白天需要按场景补涂。"},
        ],
    }
    dom = {
        "request_id": request["request_id"],
        "presentation_mode": contract["mode"],
        "legacy_message_count": 0,
        "legacy_product_card_count": 0,
        "turn_presentation_root_count": 1,
        "visible_section_kinds": ["answer"],
        "section_blocks": [
            {"kind": "answer", "text": "白天需要按场景补涂。"},
        ],
        "inline_product_ids": [],
        "visible_product_ids": [],
        "shelf_product_ids": [],
        "presentation_text": "白天需要按场景补涂。",
    }
    valid_stream = _presentation_stream(contract)
    payloads = {
        "request.json": json.dumps(request),
        "stream.sse": stream if stream is not None else valid_stream,
        "presentation-contract.json": json.dumps(contract),
        "terminal-dom.json": json.dumps(dom),
        "screenshot.png": _png_bytes(8, 5),
        "console.json": "[]",
        "network.json": "[]",
    }
    _write_bundle_payloads(turn_dir, payloads)


def _write_complete_release_evidence(root: Path) -> Path:
    def write_json(path: Path, payload: object) -> None:
        path.write_text(
            json.dumps(payload, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    attempt_root = root / "release-attempt-01"
    attempt_root.mkdir()
    identity = attempt_root / mainline_audit.RUNTIME_IDENTITY_FILENAME
    identity.write_text('{"runtime":"bound"}\n', encoding="utf-8")
    fixture_by_mode = {
        "explore_recommendation": "fixture-explore-recommendation",
        "fit_recommendation": "fixture-fit-recommendation",
        "product_knowledge": "fixture-product-knowledge",
        "comparison": "fixture-comparison",
        "image_identity": "fixture-image-identity",
        "image_fit_recommendation": (
            "fixture-image-fit-recommendation"
        ),
        "image_comparison": "fixture-multi-image-comparison",
    }
    counter_keys = (
        "serious_failure_count",
        "frontend_contract_violation_count",
        "wrong_binding_count",
        "unaligned_price_specification_count",
        "copywriter_fallback_count",
        "invalid_clarification_count",
    )
    expected_turns: list[dict[str, object]] = []
    for viewport, dimensions in mainline_audit.VIEWPORTS.items():
        browser_root = attempt_root / f"browser-{viewport}"
        browser_root.mkdir()
        trajectory_rows: list[dict[str, object]] = []
        for trajectory in mainline_audit.RELEASE_TRAJECTORIES:
            turn = trajectory.turns[0]
            relative = Path(trajectory.trajectory_id) / turn.turn_id
            turn_dir = browser_root / relative
            turn_dir.mkdir(parents=True)
            turn_id = f"{trajectory.trajectory_id}-{turn.turn_id}"
            request_id = f"request-{viewport}-{trajectory.trajectory_id}"
            stream = fixture_sse_bytes(
                fixture_by_mode[str(trajectory.release_mode)]
            )
            events = mainline_audit._sse_events_from_sse(
                stream.decode("utf-8")
            )
            contract = next(
                payload
                for event, payload in events
                if event == "presentation_contract"
            )
            sections = tuple(contract["sections"])
            visible_ids = list(contract["visible_product_ids"])
            inline_ids = [
                section["product_id"]
                for section in sections
                if section.get("kind") == "product"
            ]
            section_blocks = [
                {
                    "kind": section["kind"],
                    "text": " ".join(
                        mainline_audit._required_section_text(section)
                    ),
                }
                for section in sections
            ]
            write_json(
                turn_dir / "request.json",
                {
                    "turn_id": turn_id,
                    "request_id": request_id,
                    "user_message": turn.message,
                    "viewport": dimensions,
                },
            )
            (turn_dir / "stream.sse").write_bytes(stream)
            write_json(
                turn_dir / "presentation-contract.json",
                contract,
            )
            write_json(
                turn_dir / "terminal-dom.json",
                {
                    "request_id": request_id,
                    "presentation_mode": contract["mode"],
                    "visible_section_kinds": [
                        section["kind"] for section in sections
                    ],
                    "section_blocks": section_blocks,
                    "inline_product_ids": inline_ids,
                    "visible_product_ids": visible_ids,
                    "shelf_product_ids": visible_ids,
                    "legacy_message_count": 0,
                    "legacy_product_card_count": 0,
                    "turn_presentation_root_count": 1,
                    "comparison_table_count": int(
                        contract["mode"] == "comparison"
                    ),
                    "presentation_text": " ".join(
                        mainline_audit.required_public_text(sections)
                    ),
                },
            )
            (turn_dir / "screenshot.png").write_bytes(
                _png_bytes(dimensions["width"], dimensions["height"])
            )
            write_json(turn_dir / "console.json", [])
            write_json(turn_dir / "network.json", [])
            counters = {key: 0 for key in counter_keys}
            trajectory_rows.append({
                "trajectory_id": trajectory.trajectory_id,
                "turns": [
                    {
                        "turn_id": turn.turn_id,
                        "directory": relative.as_posix(),
                        "release_counters": counters,
                    }
                ],
                "turn_count": 1,
                "invalid_clarification_count": 0,
            })
            expected_turns.append({
                "viewport": viewport,
                "mode": trajectory.release_mode,
                "turn_id": turn_id,
                "directory": (
                    Path(f"browser-{viewport}") / relative
                ).as_posix(),
            })
        write_json(
            browser_root / "summary.json",
            {
                "schema_version": (
                    "guide-mainline-contract-browser-audit-v1"
                ),
                "trajectory_set": "release",
                "viewport": viewport,
                "passed": True,
                "turn_count": len(mainline_audit.RELEASE_TRAJECTORIES),
                "invalid_clarification_count": 0,
                "trajectories": trajectory_rows,
            },
        )
    mainline_root = attempt_root / "mainline-browser"
    mainline_root.mkdir()
    summary_path = mainline_root / "summary.json"
    artifact_sha256 = {
        path.relative_to(root).as_posix(): sha256(
            path.read_bytes()
        ).hexdigest()
        for directory in (
            attempt_root / "browser-desktop",
            attempt_root / "browser-mobile",
            mainline_root,
        )
        for path in sorted(directory.rglob("*"))
        if path.is_file() and path != summary_path
    }
    write_json(
        summary_path,
        {
            "schema_version": (
                "guide-mainline-contract-browser-audit-v1"
            ),
            "trajectory_set": "release",
            "viewport": "all",
            "turns": expected_turns,
            "turn_count": 14,
            **{key: 0 for key in counter_keys},
            "artifact_sha256": artifact_sha256,
            "passed": True,
            "runtime_identity_sha256": sha256(
                identity.read_bytes()
            ).hexdigest(),
            "runtime_proof_sha256": "2" * 64,
            "runtime_attestation_sha256": "3" * 64,
        },
    )
    return attempt_root


def test_audit_bundle_rejects_presentation_stream_without_end(
    tmp_path: Path,
) -> None:
    _write_minimal_presentation_bundle(
        tmp_path,
        stream=(
            "event: start\n"
            "data: {\"session_id\":\"terminal-sequence\"}\n\n"
            "event: presentation_contract\n"
            "data: {\"mode\":\"general_knowledge\","
            "\"visible_product_ids\":[],"
            "\"sections\":[{\"kind\":\"answer\","
            "\"copy_text\":\"白天需要按场景补涂。\"}]}\n\n"
        ),
    )

    with pytest.raises(AuditBundleError, match="stream lifecycle"):
        validate_audit_bundle(
            tmp_path,
            expected_turn_id="terminal-sequence-001",
        )


def test_audit_bundle_rejects_non_png_screenshot(
    tmp_path: Path,
) -> None:
    _write_minimal_presentation_bundle(tmp_path)
    (tmp_path / "screenshot.png").write_bytes(b"x")

    with pytest.raises(AuditBundleError, match="PNG"):
        validate_audit_bundle(
            tmp_path,
            expected_turn_id="terminal-sequence-001",
        )


def test_screenshot_validator_decodes_png_filters_zero_through_four(
    tmp_path: Path,
) -> None:
    screenshot = tmp_path / "screenshot.png"
    screenshot.write_bytes(_png_bytes(16, 10))

    mainline_audit._validate_screenshot_png(
        screenshot,
        request={},
    )


@pytest.mark.parametrize(
    ("solid_color", "nearly_blank"),
    (
        ((255, 255, 255), False),
        ((24, 96, 160), False),
        (None, True),
    ),
)
def test_screenshot_validator_rejects_empty_visual_content(
    tmp_path: Path,
    solid_color: tuple[int, int, int] | None,
    nearly_blank: bool,
) -> None:
    screenshot = tmp_path / "screenshot.png"
    screenshot.write_bytes(
        _png_bytes(
            32,
            20,
            solid_color=solid_color,
            nearly_blank=nearly_blank,
        )
    )

    with pytest.raises(AuditBundleError, match="visual content"):
        mainline_audit._validate_screenshot_png(
            screenshot,
            request={},
        )


def test_fixture_sandbox_audit_rejects_empty_netlog_for_browser_request(
    tmp_path: Path,
) -> None:
    nonce = "e" * 64
    netlog = tmp_path / "chromium-netlog.json"
    netlog.write_text('{"events":[]}\n', encoding="utf-8")

    with pytest.raises(AuditBundleError, match="Chromium network log"):
        mainline_audit._build_fixture_sandbox_audit(
            base_url="http://127.0.0.1:8820",
            browser_requests=[
                {
                    "url": (
                        "http://127.0.0.1:8820/api/v1/chat/stream"
                    ),
                    "method": "POST",
                    "resource_type": "fetch",
                }
            ],
            netlog_path=netlog,
            sandbox_profile=mainline_audit._fixture_sandbox_profile(
                nonce
            ),
            measurement_nonce=nonce,
            seatbelt_raw=_valid_seatbelt_raw(nonce),
            logger_stderr=b"",
            logger_returncode=0,
            sandbox_process_group_id=4100,
            process_group_quiescent=True,
        )


def test_fixture_sandbox_audit_rejects_empty_netlog_without_requests(
    tmp_path: Path,
) -> None:
    nonce = "f" * 64
    netlog = tmp_path / "chromium-netlog.json"
    netlog.write_text('{"events":[]}\n', encoding="utf-8")

    with pytest.raises(AuditBundleError, match="Chromium network log is empty"):
        mainline_audit._build_fixture_sandbox_audit(
            base_url="http://127.0.0.1:8820",
            browser_requests=[],
            netlog_path=netlog,
            sandbox_profile=mainline_audit._fixture_sandbox_profile(
                nonce
            ),
            measurement_nonce=nonce,
            seatbelt_raw=_valid_seatbelt_raw(nonce),
            logger_stderr=b"",
            logger_returncode=0,
            sandbox_process_group_id=4100,
            process_group_quiescent=True,
        )


def test_fixture_stream_post_cannot_evade_netlog_binding_as_document(
    tmp_path: Path,
) -> None:
    nonce = "1" * 64
    netlog = tmp_path / "chromium-netlog.json"
    netlog.write_text(
        json.dumps({
            "events": [
                {
                    "params": {
                        "url": "http://127.0.0.1:8820/chat",
                    }
                }
            ]
        }),
        encoding="utf-8",
    )

    with pytest.raises(AuditBundleError, match="does not bind"):
        mainline_audit._build_fixture_sandbox_audit(
            base_url="http://127.0.0.1:8820",
            browser_requests=[
                {
                    "url": (
                        "http://127.0.0.1:8820/api/v1/chat/stream"
                    ),
                    "method": "POST",
                    "resource_type": "document",
                }
            ],
            netlog_path=netlog,
            sandbox_profile=mainline_audit._fixture_sandbox_profile(
                nonce
            ),
            measurement_nonce=nonce,
            seatbelt_raw=_valid_seatbelt_raw(nonce),
            logger_stderr=b"",
            logger_returncode=0,
            sandbox_process_group_id=4100,
            process_group_quiescent=True,
        )


def test_fixture_sandbox_audit_rejects_unknown_resource_type(
    tmp_path: Path,
) -> None:
    nonce = "2" * 64
    netlog = tmp_path / "chromium-netlog.json"
    netlog.write_text(
        '{"events":[{"params":{"url":"http://127.0.0.1:8820/chat"}}]}\n',
        encoding="utf-8",
    )

    with pytest.raises(AuditBundleError, match="resource type"):
        mainline_audit._build_fixture_sandbox_audit(
            base_url="http://127.0.0.1:8820",
            browser_requests=[
                {
                    "url": "http://127.0.0.1:8820/chat",
                    "method": "GET",
                    "resource_type": "caller_authored_pass",
                }
            ],
            netlog_path=netlog,
            sandbox_profile=mainline_audit._fixture_sandbox_profile(
                nonce
            ),
            measurement_nonce=nonce,
            seatbelt_raw=_valid_seatbelt_raw(nonce),
            logger_stderr=b"",
            logger_returncode=0,
            sandbox_process_group_id=4100,
            process_group_quiescent=True,
        )


def test_fixture_evidence_is_explicitly_frontend_only() -> None:
    assert mainline_audit.FIXTURE_EVIDENCE_SCOPE == (
        "frontend_fixture_only"
    )
    assert mainline_audit.FIXTURE_BACKEND_PATH_CLAIM is False


def test_audit_bundle_rejects_presentation_stream_with_error(
    tmp_path: Path,
) -> None:
    _write_minimal_presentation_bundle(
        tmp_path,
        stream=(
            "event: start\n"
            "data: {\"session_id\":\"terminal-sequence\"}\n\n"
            "event: presentation_contract\n"
            "data: {\"mode\":\"general_knowledge\","
            "\"visible_product_ids\":[],"
            "\"sections\":[{\"kind\":\"answer\","
            "\"copy_text\":\"白天需要按场景补涂。\"}]}\n\n"
            "event: error\n"
            "data: {\"error\":\"GUIDE_INTERNAL_ERROR\"}\n\n"
            "event: end\n"
            "data: {\"conversation_version\":1}\n\n"
        ),
    )

    with pytest.raises(AuditBundleError, match="stream lifecycle"):
        validate_audit_bundle(
            tmp_path,
            expected_turn_id="terminal-sequence-001",
        )


@pytest.mark.parametrize(
    "extra_event",
    (
        (
            "event: clarify\n"
            "data: {\"question\":\"多余追问\","
            "\"clarification_code\":\"goal\"}\n\n"
        ),
        (
            "event: message\n"
            "data: {\"content\":\"legacy answer\"}\n\n"
        ),
    ),
)
def test_audit_bundle_rejects_second_public_terminal_owner(
    tmp_path: Path,
    extra_event: str,
) -> None:
    contract = {
        "mode": "general_knowledge",
        "visible_product_ids": [],
        "sections": [
            {"kind": "answer", "copy_text": "白天需要按场景补涂。"},
        ],
    }
    _write_minimal_presentation_bundle(
        tmp_path,
        stream=(
            "event: start\n"
            "data: {\"session_id\":\"terminal-sequence\"}\n\n"
            "event: presentation_contract\n"
            f"data: {json.dumps(contract)}\n\n"
            f"{extra_event}"
            "event: end\n"
            "data: {\"conversation_version\":1}\n\n"
        ),
    )

    with pytest.raises(AuditBundleError, match="terminal ownership"):
        validate_audit_bundle(
            tmp_path,
            expected_turn_id="terminal-sequence-001",
        )
    counters = mainline_audit.derive_release_turn_counters(tmp_path)
    assert counters["serious_failure_count"] == 1
    assert counters["frontend_contract_violation_count"] == 1


def test_audit_bundle_rejects_nonempty_malformed_sse_block(
    tmp_path: Path,
) -> None:
    contract = {
        "mode": "general_knowledge",
        "visible_product_ids": [],
        "sections": [
            {"kind": "answer", "copy_text": "白天需要按场景补涂。"},
        ],
    }
    _write_minimal_presentation_bundle(
        tmp_path,
        stream=_presentation_stream(contract) + "malformed\n\n",
    )

    with pytest.raises(AuditBundleError, match="stream event"):
        validate_audit_bundle(
            tmp_path,
            expected_turn_id="terminal-sequence-001",
        )
    counters = mainline_audit.derive_release_turn_counters(tmp_path)
    assert counters["serious_failure_count"] == 1
    assert counters["frontend_contract_violation_count"] == 1


@pytest.mark.parametrize(
    "stream",
    [
        (
            "event: start\n"
            "data: {\"session_id\":\"terminal-sequence\"}\n\n"
            "event: presentation_contract\n"
            "data: {\"mode\":\"general_knowledge\","
            "\"visible_product_ids\":[],"
            "\"sections\":[{\"kind\":\"answer\","
            "\"copy_text\":\"白天需要按场景补涂。\"}]}\n\n"
        ),
        (
            "event: start\n"
            "data: {\"session_id\":\"terminal-sequence\"}\n\n"
            "event: presentation_contract\n"
            "data: {\"mode\":\"general_knowledge\","
            "\"visible_product_ids\":[],"
            "\"sections\":[{\"kind\":\"answer\","
            "\"copy_text\":\"白天需要按场景补涂。\"}]}\n\n"
            "event: error\n"
            "data: {\"error\":\"GUIDE_INTERNAL_ERROR\"}\n\n"
            "event: end\n"
            "data: {\"conversation_version\":1}\n\n"
        ),
    ],
)
def test_release_turn_counters_fail_closed_on_invalid_stream_lifecycle(
    tmp_path: Path,
    stream: str,
) -> None:
    _write_minimal_presentation_bundle(tmp_path, stream=stream)

    counters = mainline_audit.derive_release_turn_counters(tmp_path)

    assert counters["serious_failure_count"] == 1
    assert counters["frontend_contract_violation_count"] == 1


def test_chat_marks_assistant_wrapper_with_request_id() -> None:
    html = (ROOT / "app/static/chat.html").read_text(
        encoding="utf-8"
    )

    assert (
        "typingDiv.dataset.guideRequestId = requestContext.requestId"
        in html
    )


def test_chat_uses_only_local_icon_runtime() -> None:
    html = (ROOT / "app/static/chat.html").read_text(
        encoding="utf-8"
    )

    assert "https://unpkg.com/feather-icons" not in html
    assert 'src="/static/vendor/feather.min.js"' in html
    assert (
        ROOT / "app/static/vendor/feather.min.js"
    ).is_file()


def test_zero_api_fixture_streams_are_typed_terminal_contracts() -> None:
    assert FIXTURE_TURN_IDS == (
        "fixture-explore-recommendation",
        "fixture-fit-recommendation",
        "fixture-fit-clarification",
        "fixture-product-knowledge",
        "fixture-comparison",
        "fixture-image-identity",
        "fixture-image-fit-recommendation",
        "fixture-multi-image-comparison",
    )
    for turn_id in FIXTURE_TURN_IDS:
        raw = fixture_sse_bytes(turn_id)
        assert (
            raw.count(b"event: presentation_contract\n")
            + raw.count(b"event: clarify\n")
        ) == 1
        assert raw.endswith(b"event: end\ndata: {\"conversation_version\":1}\n\n")
    multi_image = fixture_sse_bytes(
        "fixture-multi-image-comparison"
    )
    assert multi_image.count(b"event: image_observation\n") == 2
    clarification = fixture_sse_bytes("fixture-fit-clarification")
    assert b"event: clarify\n" in clarification
    assert b"event: presentation_contract\n" not in clarification
    assert b"event: card_display_contract\n" not in clarification
    assert b"event: products\n" not in clarification


@pytest.mark.parametrize(
    ("turn_id", "expected_message", "expected_file_names"),
    [
        (
            "fixture-image-identity",
            "",
            ("product-38-index-control.png",),
        ),
        (
            "fixture-image-fit-recommendation",
            "给我找一款最适合油敏肌、换季泛红时用的相似精华",
            ("product-38-index-control.png",),
        ),
        (
            "fixture-multi-image-comparison",
            "比较这两张图里的商品",
            (
                "product-38-index-control.png",
                "jd_v3_10069603621835.png",
            ),
        ),
    ],
)
def test_fixture_image_turns_prepare_real_upload_inputs(
    turn_id: str,
    expected_message: str,
    expected_file_names: tuple[str, ...],
) -> None:
    class PageProbe:
        def __init__(self) -> None:
            self.files: tuple[str, ...] = ()
            self.message: str | None = None
            self.preview_count: int | None = None

        def set_input_files(
            self,
            selector: str,
            paths: list[str],
        ) -> None:
            assert selector == "#imageInput"
            self.files = tuple(paths)

        def wait_for_function(
            self,
            expression: str,
            *,
            arg: int,
            timeout: int,
        ) -> None:
            assert "#imagePreview .preview-item" in expression
            assert timeout == 10_000
            self.preview_count = arg

        def fill(self, selector: str, message: str) -> None:
            assert selector == "#chatInput"
            self.message = message

    page = PageProbe()

    mainline_audit._prepare_fixture_turn_inputs(page, turn_id)

    assert tuple(Path(path).name for path in page.files) == (
        expected_file_names
    )
    assert all(Path(path).is_file() for path in page.files)
    assert page.preview_count == len(expected_file_names)
    assert page.message == (expected_message or None)


def test_multi_image_fixture_declares_current_upload_evidence_source() -> None:
    events = mainline_audit._sse_events_from_sse(
        fixture_sse_bytes(
            "fixture-multi-image-comparison"
        ).decode("utf-8")
    )
    decision = next(
        payload
        for event_name, payload in events
        if event_name == "decision_process"
    )

    assert decision["comparison_data"]["context_source"] == "current_upload"


def test_fixture_route_serves_feedback_target_from_the_same_stream() -> None:
    class FakeRequest:
        url = (
            "http://127.0.0.1:8820/api/v1/chat/sessions/"
            "fixture-session/feedback-target"
        )

    class FakeRoute:
        request = FakeRequest()

        def __init__(self) -> None:
            self.fetch_calls = 0
            self.fulfilled: dict[str, object] = {}

        def fetch(self) -> object:
            self.fetch_calls += 1
            return object()

        def fulfill(self, **kwargs: object) -> None:
            self.fulfilled = kwargs

    class FakePage:
        def __init__(self) -> None:
            self.handlers = []

        def route(self, pattern: str, handler: object) -> None:
            self.handlers.append((pattern, handler))

    page = FakePage()
    mainline_audit._install_fixture_route(
        page,
        stream=fixture_sse_bytes("fixture-explore-recommendation"),
    )
    route = FakeRoute()

    page.handlers[0][1](route)

    assert route.fetch_calls == 0
    assert route.fulfilled["status"] == 200
    assert route.fulfilled["content_type"] == "application/json"
    assert json.loads(str(route.fulfilled["body"])) == {
        "conversation_version": 1,
        "displayed_product_ids": [38, 91],
        "profile_version": None,
    }


def test_fixture_clarification_route_has_no_feedback_target() -> None:
    class FakeRequest:
        url = (
            "http://127.0.0.1:8820/api/v1/chat/sessions/"
            "fixture-session/feedback-target"
        )

    class FakeRoute:
        request = FakeRequest()

        def __init__(self) -> None:
            self.fetch_calls = 0
            self.fulfilled: dict[str, object] = {}

        def fetch(self) -> object:
            self.fetch_calls += 1
            return object()

        def fulfill(self, **kwargs: object) -> None:
            self.fulfilled = kwargs

    class FakePage:
        def __init__(self) -> None:
            self.handlers = []

        def route(self, pattern: str, handler: object) -> None:
            self.handlers.append((pattern, handler))

    page = FakePage()
    mainline_audit._install_fixture_route(
        page,
        stream=fixture_sse_bytes("fixture-fit-clarification"),
    )
    route = FakeRoute()

    page.handlers[0][1](route)

    assert route.fetch_calls == 0
    assert route.fulfilled["status"] == 404


def test_fixture_route_preserves_image_bundle_multipart_upload() -> None:
    class FakeRequest:
        url = "http://127.0.0.1:8820/api/v1/chat/image-bundles"

    class FakeRoute:
        request = FakeRequest()

        def __init__(self) -> None:
            self.continued = False

        def continue_(self) -> None:
            self.continued = True

    class FakePage:
        def __init__(self) -> None:
            self.handlers = []

        def route(self, pattern: str, handler: object) -> None:
            self.handlers.append((pattern, handler))

    page = FakePage()
    mainline_audit._install_fixture_route(
        page,
        stream=fixture_sse_bytes("fixture-image-identity"),
    )
    route = FakeRoute()

    page.handlers[0][1](route)

    assert route.continued is True


def test_fixture_chromium_disables_external_dns_transport() -> None:
    args = mainline_audit._fixture_chromium_args(
        Path("/tmp/task11-chromium-netlog.json")
    )

    assert "--disable-quic" in args
    assert "--disable-features=AsyncDns,UseDnsHttpsSvcb" in args


def test_release_trajectories_cover_all_required_terminal_modes() -> None:
    trajectories = mainline_audit.RELEASE_TRAJECTORIES
    assert len(trajectories) == 7
    assert {
        trajectory.release_mode
        for trajectory in trajectories
    } == {
        "explore_recommendation",
        "fit_recommendation",
        "product_knowledge",
        "comparison",
        "image_identity",
        "image_fit_recommendation",
        "image_comparison",
    }
    fit = next(
        trajectory
        for trajectory in trajectories
        if trajectory.release_mode == "fit_recommendation"
    )
    assert fit.turns[0].message == (
        "给我推荐一款最适合油敏肌、换季泛红的"
        " 900 到 1100 元精华"
    )


def test_demo_trajectories_cover_seven_modes_and_twenty_one_turns() -> None:
    trajectories = mainline_audit.DEMO_TRAJECTORIES

    assert len(trajectories) == 7
    assert sum(len(item.turns) for item in trajectories) == 21
    assert {
        trajectory.release_mode
        for trajectory in trajectories
    } == {
        "explore_recommendation",
        "fit_recommendation",
        "product_knowledge",
        "comparison",
        "image_identity",
        "image_fit_recommendation",
        "image_comparison",
    }
    comparison = next(
        trajectory
        for trajectory in trajectories
        if trajectory.release_mode == "comparison"
    )
    assert tuple(turn.message for turn in comparison.turns) == (
        "帮我对比兰蔻小黑瓶和小棕瓶",
        "那哪个更适合油敏肌？",
        "继续比较这两款，不考虑肤质，只看功效、质地和价格",
    )
    fit = next(
        trajectory
        for trajectory in trajectories
        if trajectory.release_mode == "fit_recommendation"
    )
    assert fit.turns[0].allow_clarification is False
    assert tuple(turn.message for turn in fit.turns) == (
        "给我推荐一款最适合修护屏障、清爽不黏需求的"
        " 900 到 1100 元精华",
        "功效仍然优先修护屏障，但肤感改成更水润，还是只要一款",
        "预算降到八百，其他要求不变，还是只要一款",
    )
    image_fit = next(
        trajectory
        for trajectory in trajectories
        if trajectory.release_mode == "image_fit_recommendation"
    )
    assert image_fit.turns[0].allow_clarification is True
    assert tuple(turn.message for turn in image_fit.turns) == (
        "给我找一款最适合油敏肌、换季泛红时用的相似精华",
        "不考虑肤质，继续参考第一轮上传的图片，"
        "只推荐一款修护屏障、清爽不黏的相似精华",
        "预算改成三百以内，其他要求不变，还是只要一款",
    )


def test_general_knowledge_trajectories_cover_six_observed_probes() -> None:
    trajectories = mainline_audit.GENERAL_KNOWLEDGE_TRAJECTORIES

    assert [trajectory.trajectory_id for trajectory in trajectories] == [
        "gk-multi-ingredient",
        "gk-sensitive-identification",
        "gk-acid-active-reaction",
        "gk-sunscreen-reapplication",
        "gk-vitamin-c-daytime",
        "gk-oily-summer-moisturizer",
    ]
    assert [trajectory.turns[0].message for trajectory in trajectories] == [
        "烟酰胺和A醇有什么区别，能一起用吗？",
        "怎么判断自己是不是敏感肌？",
        "刷酸后爆皮刺痛应该怎么办？",
        "防晒为什么过几个小时还要补涂？",
        "维C白天到底能不能用？",
        "油皮夏天应该怎么选面霜？",
    ]
    assert [trajectory.turns[0].expected_mode for trajectory in trajectories] == [
        "general_knowledge",
        "general_knowledge",
        "consultation",
        "general_knowledge",
        "general_knowledge",
        "general_knowledge",
    ]


def _general_knowledge_validation_inputs():
    source_13 = "data/knowledge_docs/13-烟酰胺适合谁.md"
    source_14 = "data/knowledge_docs/14-视黄醇A醇适合谁.md"
    citation_ids = ("a" * 64, "b" * 64)
    turn = mainline_audit.BoundedBrowserTurn(
        turn_id="t1",
        message="烟酰胺和A醇有什么区别，能一起用吗？",
        expected_mode="general_knowledge",
        expected_knowledge_sources=(source_13, source_14),
        allowed_knowledge_sources=(source_13, source_14),
        expected_knowledge_sections=("关键成分/原理",),
        allowed_knowledge_sections=("关键成分/原理",),
        expected_missing_relations=("compatibility",),
    )
    event = {
        "query": "比较烟酰胺和视黄醇并询问能否叠加",
        "citations": [
            {
                "knowledge_id": citation_ids[0],
                "title": "烟酰胺适合谁",
                "section_title": "关键成分/原理",
                "public_excerpt": "烟酰胺可辅助控油和修护。",
                "source_path": source_13,
                "review_decision": "general_answer",
            },
            {
                "knowledge_id": citation_ids[1],
                "title": "视黄醇适合谁",
                "section_title": "关键成分/原理",
                "public_excerpt": "视黄醇可用于抗老和改善粗糙。",
                "source_path": source_14,
                "review_decision": "general_answer",
            },
        ],
        "coverage": {
            "required_concept_ids": ["ingredient"],
            "covered_concept_ids": ["ingredient"],
            "required_entity_ids": [
                "ingredient.niacinamide",
                "ingredient.retinol",
            ],
            "covered_entity_ids": [
                "ingredient.niacinamide",
                "ingredient.retinol",
            ],
            "required_relation_intents": [
                "difference",
                "compatibility",
            ],
            "covered_relation_intents": ["difference"],
            "missing_concept_ids": [],
            "missing_entity_ids": [],
            "missing_relation_intents": ["compatibility"],
            "complete": False,
        },
        "educational_only": True,
        "medical_escalation": False,
    }
    contract = {
        "mode": "general_knowledge",
        "responsibility": "general_knowledge",
        "sections": [
            {
                "kind": "answer",
                "copy_text": (
                    "现有可靠资料没有直接说明这组对象能否一起使用，"
                    "这里不根据各自介绍推导兼容性结论。"
                ),
            }
        ],
    }
    dom = {
        "knowledge_citation_panel_count": 1,
        "knowledge_citation_ids": list(citation_ids),
    }
    events = (("general_knowledge", event),)
    return turn, contract, events, dom


def test_general_knowledge_turn_accepts_bound_citations_and_gap() -> None:
    turn, contract, events, dom = _general_knowledge_validation_inputs()

    mainline_audit._validate_general_knowledge_turn(
        turn=turn,
        contract=contract,
        events=events,
        dom=dom,
    )


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        ("missing_source", "expected knowledge source"),
        ("missing_section", "expected knowledge section"),
        ("unlisted_source", "unlisted knowledge source"),
        ("duplicate_id", "duplicate knowledge citation"),
        ("coverage", "knowledge coverage mismatch"),
        ("unsupported_compatibility", "compatibility gap"),
        ("no_public_answer", "useful general knowledge answer"),
        ("missing_panel", "knowledge citation panel"),
    ),
)
def test_general_knowledge_turn_rejects_unusable_evidence(
    mutation: str,
    message: str,
) -> None:
    turn, contract, events, dom = _general_knowledge_validation_inputs()
    event = json.loads(json.dumps(events[0][1]))
    contract = json.loads(json.dumps(contract))
    dom = json.loads(json.dumps(dom))
    if mutation == "missing_source":
        event["citations"].pop()
    elif mutation == "missing_section":
        event["citations"][0]["section_title"] = "适合谁"
        event["citations"][1]["section_title"] = "适合谁"
    elif mutation == "unlisted_source":
        event["citations"].append({
            "knowledge_id": "c" * 64,
            "title": "面霜怎么选",
            "section_title": "怎么选",
            "public_excerpt": "按肤质选择面霜。",
            "source_path": "data/knowledge_docs/08-面霜怎么选.md",
            "review_decision": "general_answer",
        })
    elif mutation == "duplicate_id":
        event["citations"][1]["knowledge_id"] = (
            event["citations"][0]["knowledge_id"]
        )
    elif mutation == "coverage":
        event["coverage"]["missing_relation_intents"] = []
        event["coverage"]["covered_relation_intents"].append(
            "compatibility"
        )
        event["coverage"]["complete"] = True
    elif mutation == "unsupported_compatibility":
        contract["sections"][0]["copy_text"] = (
            "烟酰胺和A醇可以直接叠加使用。"
        )
    elif mutation == "no_public_answer":
        for citation in event["citations"]:
            citation["review_decision"] = "escalation_only"
            citation["public_excerpt"] = None
    elif mutation == "missing_panel":
        dom["knowledge_citation_panel_count"] = 0

    with pytest.raises(AuditBundleError, match=message):
        mainline_audit._validate_general_knowledge_turn(
            turn=turn,
            contract=contract,
            events=(("general_knowledge", event),),
            dom=dom,
        )


def test_consultation_turn_rejects_general_knowledge_event() -> None:
    _, _, events, _ = _general_knowledge_validation_inputs()
    turn = mainline_audit.BoundedBrowserTurn(
        turn_id="t1",
        message="刷酸后爆皮刺痛应该怎么办？",
        expected_mode="consultation",
    )

    with pytest.raises(
        AuditBundleError,
        match="consultation emitted general knowledge",
    ):
        mainline_audit._validate_general_knowledge_turn(
            turn=turn,
            contract={
                "mode": "consultation",
                "responsibility": "consultation",
                "sections": [{"kind": "answer", "copy_text": "请先停用。"}],
            },
            events=events,
            dom={
                "knowledge_citation_panel_count": 0,
                "knowledge_citation_ids": [],
            },
        )


def test_completed_release_browser_evidence_accepts_all_fourteen_turns(
    tmp_path: Path,
) -> None:
    attempt_root = _write_complete_release_evidence(tmp_path)

    summary = mainline_audit.validate_completed_release_browser_evidence(
        attempt_root,
        repo_root=tmp_path,
    )

    assert summary["passed"] is True
    assert summary["turn_count"] == 14
    assert summary["runtime_proof_sha256"] == "2" * 64


def test_completed_release_browser_evidence_rederives_turn_counters(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    attempt_root = _write_complete_release_evidence(tmp_path)
    real_derive = mainline_audit.derive_release_turn_counters
    calls = 0

    def derive_with_observed_fallback(
        turn_dir: Path,
        *,
        allow_clarification: bool = False,
    ) -> dict[str, int]:
        nonlocal calls
        counters = real_derive(
            turn_dir,
            allow_clarification=allow_clarification,
        )
        calls += 1
        if calls == 1:
            counters["copywriter_fallback_count"] = 1
            counters["serious_failure_count"] = 1
        return counters

    monkeypatch.setattr(
        mainline_audit,
        "derive_release_turn_counters",
        derive_with_observed_fallback,
    )

    with pytest.raises(
        mainline_audit.AuditBundleError,
        match="release browser counters",
    ):
        mainline_audit.validate_completed_release_browser_evidence(
            attempt_root,
            repo_root=tmp_path,
        )

    assert calls == 1


def test_release_turn_counters_derive_unaligned_price_from_raw_sse(
    tmp_path: Path,
) -> None:
    raw = fixture_sse_bytes("fixture-product-knowledge").replace(
        b'"specification":null',
        b'"specification":"30ml"',
    )
    events = mainline_audit._sse_events_from_sse(
        raw.decode("utf-8")
    )
    contract = next(
        payload
        for event, payload in events
        if event == "presentation_contract"
    )
    (tmp_path / "stream.sse").write_bytes(raw)
    (tmp_path / "presentation-contract.json").write_text(
        json.dumps(contract),
        encoding="utf-8",
    )
    (tmp_path / "terminal-dom.json").write_text(
        json.dumps(
            {
                "presentation_mode": contract["mode"],
                "visible_product_ids": contract["visible_product_ids"],
                "shelf_product_ids": contract["visible_product_ids"],
                "legacy_message_count": 0,
                "legacy_product_card_count": 0,
                "turn_presentation_root_count": 1,
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "console.json").write_text("[]\n", encoding="utf-8")
    (tmp_path / "network.json").write_text("[]\n", encoding="utf-8")

    counters = mainline_audit.derive_release_turn_counters(tmp_path)

    assert counters == {
        "serious_failure_count": 1,
        "frontend_contract_violation_count": 0,
        "wrong_binding_count": 1,
        "unaligned_price_specification_count": 1,
        "copywriter_fallback_count": 0,
        "invalid_clarification_count": 0,
    }


@pytest.mark.parametrize(
    ("old", "new"),
    (
        (
            '"display_name":"理肤泉新B5多效修护精华"'.encode(),
            b'"display_name":"forged product"',
        ),
        (b'"price":"294.0"', b'"price":"9999"'),
        (b'"specification":null', b'"specification":"999ml"'),
        (
            b'"image_url":"/static/images/products/'
            b'jd_v3_100160480140.png"',
            b'"image_url":"/static/images/products/forged.png"',
        ),
    ),
)
def test_release_turn_counters_reject_noncanonical_product_fields(
    tmp_path: Path,
    old: bytes,
    new: bytes,
) -> None:
    raw = fixture_sse_bytes("fixture-product-knowledge")
    assert old in raw
    raw = raw.replace(old, new)
    events = mainline_audit._sse_events_from_sse(
        raw.decode("utf-8")
    )
    contract = next(
        payload
        for event, payload in events
        if event == "presentation_contract"
    )
    (tmp_path / "stream.sse").write_bytes(raw)
    (tmp_path / "presentation-contract.json").write_text(
        json.dumps(contract),
        encoding="utf-8",
    )
    (tmp_path / "terminal-dom.json").write_text(
        json.dumps({
            "presentation_mode": contract["mode"],
            "visible_product_ids": contract["visible_product_ids"],
            "shelf_product_ids": contract["visible_product_ids"],
            "legacy_message_count": 0,
            "legacy_product_card_count": 0,
            "turn_presentation_root_count": 1,
        }),
        encoding="utf-8",
    )
    (tmp_path / "console.json").write_text("[]\n", encoding="utf-8")
    (tmp_path / "network.json").write_text("[]\n", encoding="utf-8")

    counters = mainline_audit.derive_release_turn_counters(tmp_path)

    assert counters["serious_failure_count"] == 1
    assert counters["wrong_binding_count"] == 1


@pytest.mark.parametrize(
    ("field_name", "forged_value", "groups"),
    (
        ("type", "forged_card", ("cards",)),
        ("category_profile", "suncare", ("cards", "products")),
        (
            "category_facts",
            [
                {
                    "field_key": "texture",
                    "label": "质地",
                    "value": ["forged"],
                    "state": "known",
                }
            ],
            ("cards", "products"),
        ),
        ("variant_scope", "forged-variant", ("cards", "products")),
        ("brand", "forged brand", ("cards", "products")),
        ("category", "forged category", ("cards", "products")),
        (
            "detail_url",
            "https://example.invalid/forged",
            ("cards", "products"),
        ),
        ("platform", "forged platform", ("cards", "products")),
        ("image_source_sha256", "f" * 64, ("cards", "products")),
        ("description", "forged description", ("products",)),
        ("efficacy_match", "matched", ("products",)),
        ("matched_efficacies", ["forged"], ("cards", "products")),
        ("suitable_skin", "forged skin", ("products",)),
        ("fact_warnings", ["forged_warning"], ("cards", "products")),
    ),
)
def test_release_turn_counters_reject_all_other_forged_product_fields(
    tmp_path: Path,
    field_name: str,
    forged_value: object,
    groups: tuple[str, ...],
) -> None:
    raw = _mutate_product_payload(
        fixture_sse_bytes("fixture-product-knowledge"),
        field_name=field_name,
        forged_value=forged_value,
        groups=groups,
    )
    events = mainline_audit._sse_events_from_sse(
        raw.decode("utf-8")
    )
    contract = next(
        payload
        for event, payload in events
        if event == "presentation_contract"
    )
    (tmp_path / "stream.sse").write_bytes(raw)
    (tmp_path / "presentation-contract.json").write_text(
        json.dumps(contract),
        encoding="utf-8",
    )
    (tmp_path / "terminal-dom.json").write_text(
        json.dumps({
            "presentation_mode": contract["mode"],
            "visible_product_ids": contract["visible_product_ids"],
            "shelf_product_ids": contract["visible_product_ids"],
            "legacy_message_count": 0,
            "legacy_product_card_count": 0,
            "turn_presentation_root_count": 1,
        }),
        encoding="utf-8",
    )
    (tmp_path / "console.json").write_text("[]\n", encoding="utf-8")
    (tmp_path / "network.json").write_text("[]\n", encoding="utf-8")

    counters = mainline_audit.derive_release_turn_counters(tmp_path)

    assert counters["serious_failure_count"] == 1
    assert counters["wrong_binding_count"] == 1


def test_canonical_product_accepts_category_projected_matched_efficacy() -> None:
    card = mainline_audit._fixture_card(38)
    payload = card.model_dump(mode="json")
    payload["matched_efficacies"] = ["舒缓泛红"]

    assert mainline_audit._public_product_matches_canonical(payload)


def test_canonical_product_accepts_possible_skin_match() -> None:
    source = mainline_audit._canonical_public_products()
    card = mainline_audit.build_product_card(
        source.catalog.get_presentation_facts(45),
        skin_match="matched",
    )

    assert mainline_audit._public_product_matches_canonical(
        card.model_dump(mode="json")
    )


def test_canonical_product_rejects_product_impossible_unknown_skin_match() -> None:
    source = mainline_audit._canonical_public_products()
    card = mainline_audit.build_product_card(
        source.catalog.get_presentation_facts(45),
        skin_match="unknown",
    )

    assert not mainline_audit._public_product_matches_canonical(
        card.model_dump(mode="json")
    )


def test_canonical_product_rejects_impossible_skin_match() -> None:
    card = mainline_audit._fixture_card(38)
    payload = card.model_dump(mode="json")
    payload["skin_match"] = "matched"
    forged = public_event_envelope.project_frontend_product(
        type(card).model_validate_json(json.dumps(payload))
    )
    events = (
        (
            "products",
            {
                "cards": [payload],
                "products": [forged],
            },
        ),
    )

    assert not mainline_audit._product_payloads_match_canonical(
        events=events,
        expected_product_ids=(38,),
    )


def test_canonical_product_accepts_reviewed_variant_scope() -> None:
    source = mainline_audit._canonical_public_products()
    variant_scope = "牛郎色 / SPACE COWBOY / 银河牛仔"
    card = mainline_audit.build_product_card(
        source.catalog.get_presentation_facts(
            117,
            variant_scope=variant_scope,
        ),
        skin_match="not_applicable",
    )

    assert mainline_audit._public_product_matches_canonical(
        card.model_dump(mode="json")
    )


def test_browser_audit_uses_the_production_frontend_product_projection() -> None:
    project = getattr(
        public_event_envelope,
        "project_frontend_product",
        None,
    )
    assert callable(project)
    card = mainline_audit._fixture_card(144)
    projected = project(card)
    events = (
        (
            "products",
            {
                "cards": [card.model_dump(mode="json")],
                "products": [projected],
            },
        ),
    )

    assert projected["image_url"]
    assert projected["detail_url"] == ""
    assert projected["platform"] == ""
    assert mainline_audit._product_payloads_match_canonical(
        events=events,
        expected_product_ids=(144,),
    )


def test_legacy_frontend_audit_reuses_production_product_projection() -> None:
    expected = [
        public_event_envelope.project_frontend_product(
            mainline_audit._fixture_card(product_id)
        )
        for product_id in frontend_browser_audit.PRODUCT_IDS
    ]

    assert frontend_browser_audit._products() == expected


def test_legacy_frontend_audit_accepts_single_terminal_stream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events = [
        {"event": "start", "data": {"session_id": "audit-test"}},
        {"event": "intent", "data": {"intent": "recommend"}},
        {
            "event": "presentation_contract",
            "data": {
                "telemetry": {
                    "provider": "disabled",
                }
            },
        },
        {"event": "end", "data": {"conversation_version": 1}},
    ]

    class FakeLocator:
        def __init__(self, *, count: int = 0) -> None:
            self._count = count

        def count(self) -> int:
            return self._count

        def evaluate_all(self, script: str) -> list[object]:
            del script
            return []

    class FakePage:
        def __init__(self) -> None:
            self._thinking_calls = 0

        def add_init_script(self, script: str) -> None:
            del script

        def on(self, event: str, callback) -> None:
            del event, callback

        def goto(self, url: str, *, wait_until: str) -> None:
            del url, wait_until

        def fill(self, selector: str, value: str) -> None:
            del selector, value

        def click(self, selector: str) -> None:
            del selector

        def wait_for_function(
            self,
            expression: str,
            *,
            timeout: int,
        ) -> None:
            del expression, timeout

        def evaluate(self, expression: str):
            if "__auditSseErrors" in expression:
                return []
            return events

        def screenshot(self, **kwargs) -> None:
            del kwargs

        def locator(self, selector: str) -> FakeLocator:
            if selector == ".guide-thinking-pipeline":
                self._thinking_calls += 1
                return FakeLocator(
                    count=1 if self._thinking_calls == 1 else 0
                )
            return FakeLocator()

    class FakeContext:
        def close(self) -> None:
            pass

    monkeypatch.setattr(
        frontend_browser_audit,
        "_new_page",
        lambda browser, *, viewport: (FakeContext(), FakePage()),
    )

    result = frontend_browser_audit._audit_live_sse(
        object(),
        url="http://127.0.0.1:8772/chat",
    )

    assert result["presentation_before_end"] is True
    assert result["message_count"] == 0
    assert result["event_sequence"][-2:] == [
        "presentation_contract",
        "end",
    ]
    assert result["lifecycle_valid"] is True


@pytest.mark.parametrize(
    "event_names",
    (
        (),
        ("intent", "presentation_contract", "end"),
        ("start", "start", "presentation_contract", "end"),
        ("start", "presentation_contract", "end", "stage"),
        ("start", "presentation_contract", "end", "end"),
        (
            "start",
            "presentation_contract",
            "presentation_contract",
            "end",
        ),
        ("start", "presentation_contract", "error", "end"),
        ("start", "message", "presentation_contract", "end"),
    ),
)
def test_legacy_frontend_audit_rejects_invalid_live_sse_lifecycle(
    event_names: tuple[str, ...],
) -> None:
    events = [
        {"event": event_name, "data": {}}
        for event_name in event_names
    ]

    with pytest.raises(
        AssertionError,
        match="live SSE lifecycle",
    ):
        frontend_browser_audit._validate_live_sse_lifecycle(events)


def test_legacy_frontend_fixture_has_no_message_terminal() -> None:
    assert "event: 'message'" not in frontend_browser_audit.RENDER_CASE


def test_release_summary_aggregates_measured_turn_counters(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def fake_viewport_run(
        *,
        output: Path,
        viewport: str,
        trajectories,
        **_: object,
    ) -> dict[str, object]:
        rows = []
        for index, trajectory in enumerate(trajectories):
            relative = Path(trajectory.trajectory_id) / "turn-1"
            turn_dir = output / relative
            turn_dir.mkdir(parents=True)
            (turn_dir / "presentation-contract.json").write_text(
                json.dumps(
                    {
                        "mode": "recommendation",
                        "copy_source": "authoritative",
                    }
                ),
                encoding="utf-8",
            )
            counters = {
                "serious_failure_count": 0,
                "frontend_contract_violation_count": 0,
                "wrong_binding_count": 0,
                "unaligned_price_specification_count": 0,
                "copywriter_fallback_count": 0,
                "invalid_clarification_count": 0,
            }
            if viewport == "desktop" and index == 0:
                counters["wrong_binding_count"] = 1
                counters["serious_failure_count"] = 1
            rows.append(
                {
                    "turn_id": "turn-1",
                    "directory": relative.as_posix(),
                    "release_counters": counters,
                }
            )
        return {
            "passed": True,
            "trajectories": [
                {
                    "trajectory_id": trajectory.trajectory_id,
                    "turns": [row],
                }
                for trajectory, row in zip(trajectories, rows, strict=True)
            ],
        }

    monkeypatch.setattr(
        mainline_audit,
        "run_bounded_browser_audit",
        fake_viewport_run,
    )
    output = tmp_path / "release"

    with pytest.raises(
        AuditBundleError,
        match="release browser audit failed",
    ):
        mainline_audit.run_release_browser_audit(
            base_url="http://127.0.0.1:8821",
            output=output,
            viewport="all",
            repo_root=tmp_path,
        )

    summary = json.loads(
        (output / "mainline-browser/summary.json").read_text(
            encoding="utf-8"
        )
    )
    assert summary["wrong_binding_count"] == 1
    assert summary["serious_failure_count"] == 1
    assert summary["passed"] is False


def test_release_cli_dispatches_attempt_bound_all_viewport_runner(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    context = tmp_path / "attempt-context.json"
    observed: dict[str, object] = {}

    def fake_run(**kwargs):
        observed.update(kwargs)
        return {"passed": True}

    monkeypatch.setattr(
        mainline_audit,
        "run_authorized_release_browser_audit",
        fake_run,
        raising=False,
    )

    assert mainline_audit.main([
        "--base-url",
        "http://127.0.0.1:8821",
        "--expected-manifest-sha256",
        "a" * 64,
        "--trajectory-set",
        "release",
        "--viewport",
        "all",
        "--attempt-context",
        str(context),
    ]) == 0
    assert observed == {
        "base_url": "http://127.0.0.1:8821",
        "attempt_context": context,
        "viewport": "all",
        "expected_manifest_sha256": "a" * 64,
    }


def test_fixture_audit_all_viewports_runs_desktop_then_mobile(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[tuple[Path, str]] = []

    def fake_run_fixture_browser_audit(
        *,
        base_url: str,
        output: Path,
        viewport: str,
    ) -> dict[str, object]:
        calls.append((output, viewport))
        output.mkdir(parents=True, exist_ok=False)
        return {
            "base_url": base_url,
            "viewport": viewport,
            "turn_count": len(FIXTURE_TURN_IDS),
            "passed": True,
        }

    monkeypatch.setattr(
        mainline_audit,
        "run_fixture_browser_audit",
        fake_run_fixture_browser_audit,
    )

    report = mainline_audit.run_fixture_browser_audits(
        base_url="http://127.0.0.1:8795",
        output=tmp_path / "all",
        viewport="all",
    )

    assert calls == [
        (tmp_path / "all" / "desktop", "desktop"),
        (tmp_path / "all" / "mobile", "mobile"),
    ]
    assert report["passed"] is True
    assert report["turn_count"] == len(FIXTURE_TURN_IDS) * 2
    assert report["invalid_clarification_count"] == 0
    assert (tmp_path / "all" / "summary.json").is_file()


def test_bounded_real_trajectories_are_fixed_and_image_grounded() -> None:
    trajectories = mainline_audit.BOUNDED_TRAJECTORIES

    assert [trajectory.trajectory_id for trajectory in trajectories] == [
        "bounded-text-fit",
        "bounded-text-context",
        "bounded-image-context",
    ]
    assert [turn.message for turn in trajectories[0].turns] == [
        "给我推荐一款最适合油敏肌、换季泛红的 900 到 1100 元精华",
    ]
    assert [turn.message for turn in trajectories[1].turns] == [
        "给我推荐 900 到 1100 元的精华",
        "第二款的质地适合什么肤质？",
        "我现在有点换季泛红，T 区出油，我可能是什么肤质？",
        "确认",
        "回到刚才的推荐，第一款和第二款哪个更适合我的肤质？",
    ]
    assert trajectories[2].turns[0].image_path == (
        ROOT / "tests/fixtures/guide/images/product-38-index-control.png"
    )
    assert trajectories[2].turns[0].expected_image_product_id == 38
    assert trajectories[0].turns[0].allow_clarification is True
    assert all(
        turn.allow_clarification is False
        for trajectory in trajectories[1:]
        for turn in trajectory.turns
    )
    assert [turn.message for turn in trajectories[2].turns] == [
        "",
        "给我找两款相似的，我最近换季泛红，T 区出油。",
        "图片里的 B5 和第一款哪个更适合我的肤质？",
    ]


def test_bounded_contract_rejects_copywriter_fallback() -> None:
    with pytest.raises(
        AuditBundleError,
        match="bounded smoke forbids fallback copy",
    ):
        mainline_audit.validate_bounded_contract(
            {
                "mode": "recommendation",
                "recommendation_mode": "fit",
                "copy_source": "fallback",
                "telemetry": {
                    "fallback_reason": "provider_unavailable",
                },
            },
            expected_mode="recommendation",
            expected_recommendation_mode="fit",
            expected_image_product_id=None,
            observations=(),
        )


def test_demo_contract_allows_copywriter_fallback() -> None:
    mainline_audit.validate_bounded_contract(
        {
            "mode": "single_product",
            "copy_source": "fallback",
            "telemetry": {
                "fallback_reason": "validation:internal_language",
            },
        },
        expected_mode="single_product",
        expected_recommendation_mode=None,
        expected_image_product_id=None,
        observations=(),
        allow_fallback_copy=True,
    )


def test_bounded_contract_accepts_authoritative_knowledge_copy() -> None:
    mainline_audit.validate_bounded_contract(
        {
            "mode": "product_knowledge",
            "copy_source": "authoritative",
            "telemetry": {
                "fallback_reason": None,
            },
        },
        expected_mode="product_knowledge",
        expected_recommendation_mode=None,
        expected_image_product_id=None,
        observations=(),
    )


def test_bounded_terminal_accepts_typed_clarification() -> None:
    mainline_audit.validate_bounded_contract(
        {
            "terminal_kind": "clarification",
            "clarification": {
                "question": "请补充一个更明确的使用场景。",
                "clarification_code": "goal",
                "intended_responsibility": "recommendation",
                "intended_recommendation_mode": "fit",
                "clarification_basis": "fit_selection_evidence_gap",
                "fit_gap_stage": "decision_selection",
                "fit_decision_status": "INSUFFICIENT_FOR_WINNER",
                "fit_candidate_count": 2,
                "fit_evidence_ref_count": 1,
                "fit_public_fact_count": 0,
            },
        },
        expected_mode="recommendation",
        expected_recommendation_mode="fit",
        expected_image_product_id=None,
        observations=(),
        allow_clarification=True,
    )


def test_allowed_bounded_clarification_has_zero_release_counters(
    tmp_path: Path,
) -> None:
    raw = fixture_sse_bytes("fixture-fit-clarification")
    events = mainline_audit._sse_events_from_sse(
        raw.decode("utf-8")
    )
    clarification = next(
        payload
        for event, payload in events
        if event == "clarify"
    )
    (tmp_path / "stream.sse").write_bytes(raw)
    (tmp_path / "presentation-contract.json").write_text(
        json.dumps({
            "terminal_kind": "clarification",
            "clarification": clarification,
        }),
        encoding="utf-8",
    )
    (tmp_path / "terminal-dom.json").write_text(
        json.dumps({
            "terminal_kind": "clarification",
            "presentation_mode": None,
            "visible_product_ids": [],
            "shelf_product_ids": [],
            "legacy_message_count": 0,
            "legacy_product_card_count": 0,
            "turn_presentation_root_count": 0,
            "clarification_message_count": 1,
        }),
        encoding="utf-8",
    )
    (tmp_path / "console.json").write_text("[]\n", encoding="utf-8")
    (tmp_path / "network.json").write_text("[]\n", encoding="utf-8")

    counters = mainline_audit.derive_release_turn_counters(
        tmp_path,
        allow_clarification=True,
    )

    assert counters == {
        "serious_failure_count": 0,
        "frontend_contract_violation_count": 0,
        "wrong_binding_count": 0,
        "unaligned_price_specification_count": 0,
        "copywriter_fallback_count": 0,
        "invalid_clarification_count": 0,
    }


def test_bounded_terminal_rejects_unproved_fit_clarification() -> None:
    with pytest.raises(
        AuditBundleError,
        match="invalid fit clarification",
    ):
        mainline_audit.validate_bounded_contract(
            {
                "terminal_kind": "clarification",
                "clarification": {
                    "question": "请补充一个更明确的使用场景。",
                    "clarification_code": "goal",
                },
            },
            expected_mode="recommendation",
            expected_recommendation_mode="fit",
            expected_image_product_id=None,
            observations=(),
            allow_clarification=True,
        )


def test_bounded_terminal_rejects_unexpected_clarification() -> None:
    with pytest.raises(
        AuditBundleError,
        match="unexpected clarification terminal",
    ):
        mainline_audit.validate_bounded_contract(
            {
                "terminal_kind": "clarification",
                "clarification": {
                    "question": "请补充一个更明确的使用场景。",
                    "clarification_code": "goal",
                },
            },
            expected_mode="recommendation",
            expected_recommendation_mode="explore",
            expected_image_product_id=None,
            observations=(),
            allow_clarification=False,
        )


def test_bounded_runner_stops_after_first_trajectory_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[str] = []

    def fail_first_trajectory(
        *,
        trajectory: object,
        **_: object,
    ) -> dict[str, object]:
        calls.append(trajectory.trajectory_id)
        raise AuditBundleError("bounded smoke forbids fallback copy")

    monkeypatch.setattr(
        mainline_audit,
        "_run_bounded_browser_trajectory",
        fail_first_trajectory,
        raising=False,
    )

    with pytest.raises(
        AuditBundleError,
        match="bounded smoke forbids fallback copy",
    ):
        mainline_audit.run_bounded_browser_audit(
            base_url="http://127.0.0.1:8821",
            output=tmp_path / "bounded",
            viewport="desktop",
        )

    assert calls == ["bounded-text-fit"]


def test_authorized_bounded_verifies_and_consumes_before_browser(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    context_path = tmp_path / "attempt-context.json"
    output = tmp_path / "bounded-smoke-attempt-02"
    output.mkdir()
    readiness_path = tmp_path / "readiness.json"
    ledger_path = tmp_path / "ledger.json"
    calls: list[str] = []
    context = {
        "output_directory": str(output),
        "readiness_path": str(readiness_path),
        "ledger_path": str(ledger_path),
    }
    context_path.write_text(
        json.dumps(context) + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        mainline_audit,
        "read_attempt_context",
        lambda *args, **kwargs: calls.append("read") or context,
    )
    monkeypatch.setattr(
        mainline_audit,
        "verify_task11_readiness",
        lambda **kwargs: calls.append("verify") or {},
    )
    runtime_proof = {
        "runtime_identity_sha256": "1" * 64,
        "runtime_proof_sha256": "2" * 64,
        "runtime_attestation_sha256": "3" * 64,
    }
    consumption_kwargs: dict[str, object] = {}

    def consume_runtime_bound(*args, **kwargs):
        calls.append("consume-runtime")
        consumption_kwargs.update(kwargs)
        return runtime_proof

    monkeypatch.setattr(
        mainline_audit,
        "consume_runtime_bound_attempt",
        consume_runtime_bound,
        raising=False,
    )

    def run_browser(**kwargs):
        calls.append("browser")
        assert kwargs["runtime_capability"] == "2" * 64
        browser_output = Path(str(kwargs["output"]))
        browser_output.mkdir()
        (browser_output / "summary.json").write_text(
            "{}\n",
            encoding="utf-8",
        )
        return {"passed": True, "invalid_clarification_count": 0}

    monkeypatch.setattr(
        mainline_audit,
        "run_bounded_browser_audit",
        run_browser,
    )
    monkeypatch.setattr(
        mainline_audit,
        "complete_attempt",
        lambda *args, **kwargs: calls.append("complete") or {},
    )

    report = mainline_audit.run_authorized_bounded_browser_audit(
        base_url="http://127.0.0.1:8821",
        attempt_context=context_path,
        viewport="desktop",
        expected_manifest_sha256="a" * 64,
    )

    assert report["passed"] is True
    assert report["runtime_attestation_sha256"] == "3" * 64
    assert consumption_kwargs["base_url"] == "http://127.0.0.1:8821"
    assert calls == [
        "read",
        "verify",
        "consume-runtime",
        "browser",
        "complete",
    ]


def test_authorized_bounded_records_structured_first_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    context_path = tmp_path / "attempt-context.json"
    output = tmp_path / "bounded-smoke-attempt-02"
    output.mkdir()
    readiness_path = tmp_path / "readiness.json"
    ledger_path = tmp_path / "ledger.json"
    context = {
        "output_directory": str(output),
        "readiness_path": str(readiness_path),
        "ledger_path": str(ledger_path),
    }
    context_path.write_text(json.dumps(context), encoding="utf-8")
    completions: list[dict[str, object]] = []

    monkeypatch.setattr(
        mainline_audit,
        "read_attempt_context",
        lambda *args, **kwargs: context,
    )
    monkeypatch.setattr(
        mainline_audit,
        "verify_task11_readiness",
        lambda **kwargs: {},
    )
    monkeypatch.setattr(
        mainline_audit,
        "consume_runtime_bound_attempt",
        lambda *args, **kwargs: {
            "runtime_identity_sha256": "1" * 64,
            "runtime_proof_sha256": "2" * 64,
            "runtime_attestation_sha256": "3" * 64,
        },
    )

    def fail_browser(**_: object) -> dict[str, object]:
        raise mainline_audit.BoundedAuditFailure(
            turn_id="bounded-image-context-t1",
            owner="presentation_provenance",
            failure_code="fallback_copy",
            evidence_directory=output / "browser-desktop" / "image",
        )

    monkeypatch.setattr(
        mainline_audit,
        "run_bounded_browser_audit",
        fail_browser,
    )
    monkeypatch.setattr(
        mainline_audit,
        "complete_attempt",
        lambda *args, **kwargs: completions.append(kwargs) or {},
    )

    with pytest.raises(mainline_audit.BoundedAuditFailure):
        mainline_audit.run_authorized_bounded_browser_audit(
            base_url="http://127.0.0.1:8821",
            attempt_context=context_path,
            viewport="desktop",
            expected_manifest_sha256="a" * 64,
        )

    assert completions == [{
        "result": "failed",
        "first_failure_turn_id": "bounded-image-context-t1",
        "first_failure_owner": "presentation_provenance",
        "failure_code": "fallback_copy",
        "evidence_directory": str(
            output / "browser-desktop" / "image"
        ),
    }]


def test_authorized_bounded_startup_failure_records_terminal_evidence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    context_path = tmp_path / "attempt-context.json"
    attempt_root = tmp_path / "bounded-smoke-attempt-02"
    attempt_root.mkdir()
    readiness_path = tmp_path / "readiness.json"
    ledger_path = tmp_path / "ledger.json"
    context = {
        "output_directory": str(attempt_root),
        "readiness_path": str(readiness_path),
        "ledger_path": str(ledger_path),
    }
    context_path.write_text(json.dumps(context), encoding="utf-8")
    monkeypatch.setattr(
        mainline_audit,
        "read_attempt_context",
        lambda *args, **kwargs: context,
    )
    monkeypatch.setattr(
        mainline_audit,
        "verify_task11_readiness",
        lambda **kwargs: {},
    )
    monkeypatch.setattr(
        mainline_audit,
        "consume_runtime_bound_attempt",
        lambda *args, **kwargs: {
            "runtime_identity_sha256": "1" * 64,
            "runtime_proof_sha256": "2" * 64,
            "runtime_attestation_sha256": "3" * 64,
        },
    )
    monkeypatch.setattr(
        mainline_audit,
        "run_bounded_browser_audit",
        lambda **_: (_ for _ in ()).throw(
            ImportError("playwright unavailable")
        ),
    )
    completions: list[dict[str, object]] = []

    def complete(*_: object, **kwargs: object) -> dict[str, object]:
        evidence = Path(str(kwargs["evidence_directory"]))
        assert evidence.is_dir()
        assert any(path.is_file() for path in evidence.rglob("*"))
        completions.append(kwargs)
        return {}

    monkeypatch.setattr(
        mainline_audit,
        "complete_attempt",
        complete,
    )

    with pytest.raises(ImportError, match="playwright unavailable"):
        mainline_audit.run_authorized_bounded_browser_audit(
            base_url="http://127.0.0.1:8821",
            attempt_context=context_path,
            viewport="desktop",
            expected_manifest_sha256="a" * 64,
        )

    failure_path = (
        attempt_root / "browser-desktop" / "runner-failure.json"
    )
    failure = json.loads(failure_path.read_text(encoding="utf-8"))
    assert failure == {
        "error_message": "playwright unavailable",
        "error_type": "ImportError",
        "failure_turn_id": "bounded-runner-startup",
        "schema_version": "guide-browser-runner-failure-v1",
    }
    assert completions == [{
        "result": "failed",
        "first_failure_turn_id": "bounded-runner-startup",
        "first_failure_owner": "browser_audit",
        "failure_code": "ImportError",
        "evidence_directory": str(
            attempt_root / "browser-desktop"
        ),
    }]


def test_cli_output_contract_separates_fixture_and_real_runs() -> None:
    output = Path("/tmp/fixture-output")
    context = Path("/tmp/attempt-context.json")

    assert mainline_audit.resolve_cli_output(
        trajectory_set="fixture",
        output=output,
        attempt_context=None,
    ) == output
    assert mainline_audit.resolve_cli_output(
        trajectory_set="demo",
        output=output,
        attempt_context=None,
    ) == output
    with pytest.raises(
        AuditBundleError,
        match="requires --attempt-context",
    ):
        mainline_audit.resolve_cli_output(
            trajectory_set="bounded",
            output=output,
            attempt_context=None,
        )
    with pytest.raises(
        AuditBundleError,
        match="forbids --output",
    ):
        mainline_audit.resolve_cli_output(
            trajectory_set="bounded",
            output=output,
            attempt_context=context,
        )


def test_demo_cli_dispatches_existing_bounded_browser_runner(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    output = tmp_path / "demo"
    observed: dict[str, object] = {}

    def fake_run(**kwargs):
        observed.update(kwargs)
        return {"passed": True}

    monkeypatch.setattr(
        mainline_audit,
        "run_bounded_browser_audit",
        fake_run,
    )

    assert mainline_audit.main([
        "--base-url",
        "http://127.0.0.1:8841",
        "--trajectory-set",
        "demo",
        "--viewport",
        "desktop",
        "--output",
        str(output),
    ]) == 0
    assert observed == {
        "base_url": "http://127.0.0.1:8841",
        "output": output,
        "viewport": "desktop",
        "trajectories": mainline_audit.DEMO_TRAJECTORIES,
        "trajectory_set": "demo",
    }


def test_general_knowledge_cli_dispatches_existing_bounded_browser_runner(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    output = tmp_path / "general-knowledge"
    observed: dict[str, object] = {}

    def fake_run(**kwargs):
        observed.update(kwargs)
        return {"passed": True}

    monkeypatch.setattr(
        mainline_audit,
        "run_bounded_browser_audit",
        fake_run,
    )

    assert mainline_audit.main([
        "--base-url",
        "http://127.0.0.1:8842",
        "--trajectory-set",
        "general_knowledge",
        "--viewport",
        "desktop",
        "--output",
        str(output),
    ]) == 0
    assert observed == {
        "base_url": "http://127.0.0.1:8842",
        "output": output,
        "viewport": "desktop",
        "trajectories": mainline_audit.GENERAL_KNOWLEDGE_TRAJECTORIES,
        "trajectory_set": "general_knowledge",
    }


def test_fixture_browser_rejects_reused_health_challenge() -> None:
    unsigned = {
        "schema_version": "guide-zero-api-runtime-challenge-v1",
        "runtime_identity_sha256": "1" * 64,
        "challenge": "2" * 64,
    }
    issued = _signed_challenge(unsigned)

    def request_json(
        method: str,
        path: str,
        payload: dict[str, object] | None,
    ) -> dict[str, object]:
        if method == "GET":
            return issued
        raise AuditBundleError("runtime health challenge already consumed")

    with pytest.raises(AuditBundleError, match="already consumed"):
        mainline_audit._consume_runtime_health_challenge(
            base_url="http://127.0.0.1:8820",
            runtime_identity_sha256="1" * 64,
            runtime_public_key=TEST_RUNTIME_PUBLIC_KEY,
            request_json=request_json,
        )


def test_fixture_browser_preserves_consumed_health_challenge_original() -> None:
    unsigned = {
        "schema_version": "guide-zero-api-runtime-challenge-v1",
        "runtime_identity_sha256": "1" * 64,
        "challenge": "2" * 64,
    }
    issued = _signed_challenge(unsigned)

    consumed = mainline_audit._consume_runtime_health_challenge(
        base_url="http://127.0.0.1:8820",
        runtime_identity_sha256="1" * 64,
        runtime_public_key=TEST_RUNTIME_PUBLIC_KEY,
        request_json=lambda method, path, payload: issued,
    )

    assert consumed == issued


def test_fixture_browser_persists_identity_and_consumed_challenge_originals(
    tmp_path: Path,
) -> None:
    identity_bytes = mainline_audit._canonical_bytes(
        {
            "runtime": "verified",
            "runtime_public_key": TEST_RUNTIME_PUBLIC_KEY,
        }
    )
    runtime_identity_sha256 = sha256(identity_bytes).hexdigest()
    unsigned = {
        "schema_version": "guide-zero-api-runtime-challenge-v1",
        "runtime_identity_sha256": runtime_identity_sha256,
        "challenge": "2" * 64,
    }
    challenge = _signed_challenge(unsigned)

    summary = mainline_audit._persist_fixture_runtime_proof(
        output=tmp_path,
        proof=mainline_audit._FixtureRuntimeProof(
            runtime_identity_bytes=identity_bytes,
            consumed_health_challenge=challenge,
        ),
    )

    assert (tmp_path / "runtime-identity.json").read_bytes() == (
        identity_bytes
    )
    assert json.loads(
        (
            tmp_path / "consumed-runtime-health-challenge.json"
        ).read_text(encoding="utf-8")
    ) == challenge
    assert summary == {
        "runtime_identity_sha256": runtime_identity_sha256,
        "consumed_health_challenge_sha256": (
            challenge["challenge_sha256"]
        ),
    }


def test_fixture_browser_never_merges_typed_runtime_proof_as_a_mapping() -> None:
    source = inspect.getsource(
        mainline_audit.run_fixture_browser_audit
    )

    assert "report.update(runtime_proof)" not in source


def test_fixture_browser_rejects_non_loopback_request() -> None:
    with pytest.raises(
        AuditBundleError,
        match="non-loopback",
    ):
        mainline_audit._validate_fixture_network_evidence(
            base_url="http://127.0.0.1:8820",
            browser_requests=[
                {
                    "url": "http://127.0.0.1:8820/chat",
                    "method": "GET",
                    "resource_type": "document",
                },
                {
                    "url": "https://unpkg.com/feather-icons",
                    "method": "GET",
                    "resource_type": "script",
                },
            ],
            process_tree_attempts=[],
        )


def test_fixture_cli_requires_runtime_identity_and_manifest_hash() -> None:
    with pytest.raises(
        SystemExit,
        match="fixture requires --expected-manifest-sha256",
    ):
        mainline_audit.main([
            "--base-url",
            "http://127.0.0.1:8820",
            "--runtime-identity",
            "/tmp/runtime.json",
            "--trajectory-set",
            "fixture",
            "--viewport",
            "desktop",
            "--output",
            "/tmp/fixture-output",
        ])

    parser = mainline_audit._parser()
    args = parser.parse_args([
        "--base-url",
        "http://127.0.0.1:8820",
        "--runtime-identity",
        "/tmp/runtime.json",
        "--expected-manifest-sha256",
        "a" * 64,
        "--trajectory-set",
        "fixture",
        "--viewport",
        "desktop",
        "--output",
        "/tmp/fixture-output",
    ])

    assert args.runtime_identity == Path("/tmp/runtime.json")
    assert args.expected_manifest_sha256 == "a" * 64


def test_fixture_runtime_verifier_receives_reviewed_manifest_sha256(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    manifest = tmp_path / "task11-candidate-manifest.json"
    identity = {
        "candidate_manifest_path": str(manifest),
        "process_identity": {"pid": 4100},
        "runtime_public_key": TEST_RUNTIME_PUBLIC_KEY,
    }
    identity_path = tmp_path / "runtime.json"
    identity_path.write_bytes(mainline_audit._canonical_bytes(identity))
    observed: dict[str, object] = {}

    def verify(**kwargs: object) -> dict[str, object]:
        observed.update(kwargs)
        return identity

    monkeypatch.setattr(
        mainline_audit,
        "verify_runtime_identity",
        verify,
    )
    monkeypatch.setattr(mainline_audit.os, "kill", lambda *_: None)
    monkeypatch.setattr(
        mainline_audit,
        "_consume_runtime_health_challenge",
        lambda **_: {
            "schema_version": "guide-zero-api-runtime-challenge-v1",
            "runtime_identity_sha256": sha256(
                identity_path.read_bytes()
            ).hexdigest(),
            "challenge": "2" * 64,
            "challenge_sha256": "3" * 64,
            "challenge_signature": "signature",
        },
    )

    mainline_audit._verified_fixture_runtime(
        base_url="http://127.0.0.1:8820",
        runtime_identity_path=identity_path,
        expected_manifest_sha256="a" * 64,
    )

    assert observed["expected_manifest_sha256"] == "a" * 64


def _seatbelt_log_event(
    *,
    message: str,
    process_path: str,
    sender_path: str | None = None,
    event_type: str = "logEvent",
) -> bytes:
    payload: dict[str, object] = {
        "eventType": event_type,
        "eventMessage": message,
        "processImagePath": process_path,
    }
    if sender_path is not None:
        payload["senderImagePath"] = sender_path
    return (
        json.dumps(payload, ensure_ascii=True, sort_keys=True) + "\n"
    ).encode("utf-8")


def _valid_seatbelt_raw(
    nonce: str,
    *,
    extra_events: tuple[bytes, ...] = (),
) -> bytes:
    root_pid = 4100
    root_child_pid = 4101
    descendant_pid = 4102
    drain_pid = 4200
    return b"".join((
        _seatbelt_log_event(
            message=f"XIAORO_SEATBELT_READY:{nonce}",
            process_path="/usr/bin/logger",
        ),
        _seatbelt_log_event(
            message=f"XIAORO_SEATBELT_BEGIN:{nonce}:{root_pid}",
            process_path="/usr/bin/logger",
        ),
        _seatbelt_log_event(
            message=(
                f"Sandbox: nc({root_child_pid}) deny(1) "
                f"network-outbound remote:*:9\n{nonce}"
            ),
            process_path="/kernel",
            sender_path=(
                "/System/Library/Extensions/Sandbox.kext/"
                "Contents/MacOS/Sandbox"
            ),
        ),
        _seatbelt_log_event(
            message=(
                f"Sandbox: nc({descendant_pid}) deny(1) "
                f"network-outbound remote:*:443\n{nonce}"
            ),
            process_path="/kernel",
            sender_path=(
                "/System/Library/Extensions/Sandbox.kext/"
                "Contents/MacOS/Sandbox"
            ),
        ),
        _seatbelt_log_event(
            message=(
                f"XIAORO_SEATBELT_CANARY:{nonce}:"
                f"root_child:{root_child_pid}:9"
            ),
            process_path="/usr/bin/logger",
        ),
        _seatbelt_log_event(
            message=(
                f"XIAORO_SEATBELT_CANARY:{nonce}:"
                f"descendant:{descendant_pid}:443"
            ),
            process_path="/usr/bin/logger",
        ),
        *extra_events,
        _seatbelt_log_event(
            message=(
                f"XIAORO_SEATBELT_CANARY:{nonce}:"
                f"drain:{drain_pid}:53"
            ),
            process_path="/usr/bin/logger",
        ),
        _seatbelt_log_event(
            message=(
                f"Sandbox: nc({drain_pid}) deny(1) "
                f"network-outbound remote:*:53\n{nonce}"
            ),
            process_path="/kernel",
            sender_path=(
                "/System/Library/Extensions/Sandbox.kext/"
                "Contents/MacOS/Sandbox"
            ),
        ),
        _seatbelt_log_event(
            message=f"XIAORO_SEATBELT_END:{nonce}:{root_pid}",
            process_path="/usr/bin/logger",
        ),
        _seatbelt_log_event(
            message=f"XIAORO_SEATBELT_DRAIN:{nonce}",
            process_path="/usr/bin/logger",
        ),
    ))


def test_fixture_sandbox_audit_uses_kernel_seatbelt_log(
    tmp_path: Path,
) -> None:
    nonce = "a" * 64
    netlog = tmp_path / "chromium-netlog.json"
    netlog.write_text(
        json.dumps(
            {
                "events": [
                    {
                        "type": 1,
                        "params": {
                            "url": "http://127.0.0.1:8820/chat",
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    sandbox_profile = mainline_audit._fixture_sandbox_profile(nonce)
    raw_seatbelt = _valid_seatbelt_raw(nonce)

    audit = mainline_audit._build_fixture_sandbox_audit(
        base_url="http://127.0.0.1:8820",
        browser_requests=[
            {
                "url": "http://127.0.0.1:8820/chat",
                "method": "GET",
                "resource_type": "document",
            }
        ],
        netlog_path=netlog,
        sandbox_profile=sandbox_profile,
        measurement_nonce=nonce,
        seatbelt_raw=raw_seatbelt,
        logger_stderr=b"",
        logger_returncode=0,
        sandbox_process_group_id=4100,
        process_group_quiescent=True,
    )

    assert audit["passed"] is True
    assert audit["browser_request_count"] == 1
    assert audit["process_tree_non_loopback_attempt_count"] == 0
    assert audit["browser_observed_non_loopback_attempt_count"] == 0
    assert audit["attempts"] == []
    assert audit["measurement"] == "macos-unified-log-seatbelt-kernel"
    assert audit["measurement_nonce"] == nonce
    assert audit["seatbelt_canary_denial_count"] == 3
    assert audit["sandbox_process_group_id"] == 4100
    assert audit["process_group_quiescent"] is True
    assert audit["seatbelt_raw_ndjson_sha256"] == sha256(
        raw_seatbelt
    ).hexdigest()
    assert audit["logger_ready"] is True
    assert audit["logger_loss_event_count"] == 0
    assert audit["netlog_sha256"] == sha256(
        netlog.read_bytes()
    ).hexdigest()


def test_fixture_sandbox_audit_rejects_child_marker_before_kernel_identity(
    tmp_path: Path,
) -> None:
    nonce = "f" * 64
    netlog = tmp_path / "chromium-netlog.json"
    netlog.write_text(
        '{"events":[{"params":{"url":"http://127.0.0.1:8820/chat"}}]}\n',
        encoding="utf-8",
    )
    events = _valid_seatbelt_raw(nonce).splitlines(keepends=True)
    root_denial_index = next(
        index
        for index, line in enumerate(events)
        if b"network-outbound remote:*:9" in line
    )
    root_marker_index = next(
        index
        for index, line in enumerate(events)
        if b":root_child:" in line
    )
    events[root_denial_index], events[root_marker_index] = (
        events[root_marker_index],
        events[root_denial_index],
    )

    with pytest.raises(AuditBundleError, match="canary delivery order"):
        mainline_audit._build_fixture_sandbox_audit(
            base_url="http://127.0.0.1:8820",
            browser_requests=[
                {
                    "url": "http://127.0.0.1:8820/chat",
                    "method": "GET",
                    "resource_type": "document",
                }
            ],
            netlog_path=netlog,
            sandbox_profile=mainline_audit._fixture_sandbox_profile(
                nonce
            ),
            measurement_nonce=nonce,
            seatbelt_raw=b"".join(events),
            logger_stderr=b"",
            logger_returncode=0,
            sandbox_process_group_id=4100,
            process_group_quiescent=True,
        )


def test_fixture_sandbox_audit_records_kernel_denied_chromium_ipv6_probe(
    tmp_path: Path,
) -> None:
    nonce = "7" * 64
    netlog = tmp_path / "chromium-netlog.json"
    netlog.write_text(
        json.dumps(
            {
                "events": [
                    {
                        "type": 1,
                        "params": {
                            "url": "http://127.0.0.1:8820/chat",
                        },
                    },
                    {
                        "type": 94,
                        "params": {
                            "address": (
                                "[2001:4860:4860::8888]:443"
                            ),
                        },
                    },
                    {
                        "type": 46,
                        "params": {
                            "address": (
                                "[2001:4860:4860::8888]:443"
                            ),
                        },
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    probe_denial = _seatbelt_log_event(
        message=(
            "Sandbox: chrome-headless-shell(4103) deny(1) "
            f"network-outbound remote:*:443\n{nonce}"
        ),
        process_path="/kernel",
        sender_path=(
            "/System/Library/Extensions/Sandbox.kext/"
            "Contents/MacOS/Sandbox"
        ),
    )
    duplicate_probe_denial = _seatbelt_log_event(
        message=(
            "1 duplicate report for Sandbox: "
            "chrome-headless-shell(4103) deny(1) "
            f"network-outbound remote:*:443\n{nonce}"
        ),
        process_path="/kernel",
        sender_path=(
            "/System/Library/Extensions/Sandbox.kext/"
            "Contents/MacOS/Sandbox"
        ),
    )

    audit = mainline_audit._build_fixture_sandbox_audit(
        base_url="http://127.0.0.1:8820",
        browser_requests=[
            {
                "url": "http://127.0.0.1:8820/chat",
                "method": "GET",
                "resource_type": "document",
            }
        ],
        netlog_path=netlog,
        sandbox_profile=mainline_audit._fixture_sandbox_profile(
            nonce
        ),
        measurement_nonce=nonce,
        seatbelt_raw=_valid_seatbelt_raw(
            nonce,
            extra_events=(probe_denial, duplicate_probe_denial),
        ),
        logger_stderr=b"",
        logger_returncode=0,
        sandbox_process_group_id=4100,
        process_group_quiescent=True,
    )

    assert audit["passed"] is True
    assert audit["attempts"] == []
    assert audit["process_tree_non_loopback_attempt_count"] == 0
    assert audit["browser_observed_non_loopback_attempt_count"] == 0
    assert audit["blocked_environmental_probe_count"] == 2
    assert audit["blocked_environmental_probe_targets"] == [
        "[2001:4860:4860::8888]:443"
    ]


def test_fixture_sandbox_audit_rejects_chromium_probe_denial_after_end(
    tmp_path: Path,
) -> None:
    nonce = "8" * 64
    netlog = tmp_path / "chromium-netlog.json"
    netlog.write_text(
        json.dumps(
            {
                "events": [
                    {
                        "type": 1,
                        "params": {
                            "url": "http://127.0.0.1:8820/chat",
                        },
                    },
                    {
                        "type": 94,
                        "params": {
                            "address": "[2001:4860:4860::8888]:443",
                        },
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    events = _valid_seatbelt_raw(nonce).splitlines(keepends=True)
    end_index = next(
        index
        for index, line in enumerate(events)
        if b"XIAORO_SEATBELT_END:" in line
    )
    probe_denial = _seatbelt_log_event(
        message=(
            "Sandbox: chrome-headless-shell(4103) deny(1) "
            f"network-outbound remote:*:443\n{nonce}"
        ),
        process_path="/kernel",
        sender_path=(
            "/System/Library/Extensions/Sandbox.kext/"
            "Contents/MacOS/Sandbox"
        ),
    )
    events.insert(end_index + 1, probe_denial)

    with pytest.raises(
        AuditBundleError,
        match="probe denial order",
    ):
        mainline_audit._build_fixture_sandbox_audit(
            base_url="http://127.0.0.1:8820",
            browser_requests=[
                {
                    "url": "http://127.0.0.1:8820/chat",
                    "method": "GET",
                    "resource_type": "document",
                }
            ],
            netlog_path=netlog,
            sandbox_profile=mainline_audit._fixture_sandbox_profile(
                nonce
            ),
            measurement_nonce=nonce,
            seatbelt_raw=b"".join(events),
            logger_stderr=b"",
            logger_returncode=0,
            sandbox_process_group_id=4100,
            process_group_quiescent=True,
        )


def test_fixture_sandbox_audit_accepts_duplicate_only_known_chromium_probe(
    tmp_path: Path,
) -> None:
    nonce = "8" * 64
    netlog = tmp_path / "chromium-netlog.json"
    netlog.write_text(
        json.dumps(
            {
                "events": [
                    {
                        "type": 1,
                        "params": {
                            "url": "http://127.0.0.1:8820/chat",
                        },
                    },
                    {
                        "type": 94,
                        "params": {
                            "address": (
                                "[2001:4860:4860::8888]:443"
                            ),
                        },
                    },
                    {
                        "type": 46,
                        "params": {
                            "address": (
                                "[2001:4860:4860::8888]:443"
                            ),
                        },
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    duplicate_probe_denial = _seatbelt_log_event(
        message=(
            "7 duplicate reports for Sandbox: "
            "chrome-headless-shell(4103) deny(1) "
            f"network-outbound remote:*:443\n{nonce}"
        ),
        process_path="/kernel",
        sender_path=(
            "/System/Library/Extensions/Sandbox.kext/"
            "Contents/MacOS/Sandbox"
        ),
    )

    audit = mainline_audit._build_fixture_sandbox_audit(
        base_url="http://127.0.0.1:8820",
        browser_requests=[
            {
                "url": "http://127.0.0.1:8820/chat",
                "method": "GET",
                "resource_type": "document",
            }
        ],
        netlog_path=netlog,
        sandbox_profile=mainline_audit._fixture_sandbox_profile(
            nonce
        ),
        measurement_nonce=nonce,
        seatbelt_raw=_valid_seatbelt_raw(
            nonce,
            extra_events=(duplicate_probe_denial,),
        ),
        logger_stderr=b"",
        logger_returncode=0,
        sandbox_process_group_id=4100,
        process_group_quiescent=True,
    )

    assert audit["passed"] is True
    assert audit["attempts"] == []
    assert audit["process_tree_non_loopback_attempt_count"] == 0
    assert audit["browser_observed_non_loopback_attempt_count"] == 0
    assert audit["blocked_environmental_probe_count"] == 2
    assert audit["blocked_environmental_probe_targets"] == [
        "[2001:4860:4860::8888]:443"
    ]


@pytest.mark.parametrize(
    ("raw_transform", "match"),
    [
        (
            lambda raw: raw.replace(
                b"XIAORO_SEATBELT_READY",
                b"XIAORO_SEATBELT_MISSING",
            ),
            "readiness marker",
        ),
        (
            lambda raw: raw.replace(
                b"network-outbound remote:*:9",
                b"network-outbound remote:*:10",
            ),
            "root canary",
        ),
        (
            lambda raw: raw.replace(
                b"network-outbound remote:*:443",
                b"network-outbound remote:*:444",
            ),
            "child canary",
        ),
        (
            lambda raw: raw.replace(
                b"network-outbound remote:*:53",
                b"network-outbound remote:*:54",
            ),
            "drain canary",
        ),
        (
            lambda raw: raw
            + _seatbelt_log_event(
                message="log stream dropped messages",
                process_path="/usr/bin/log",
                event_type="lossEvent",
            ),
            "lost events",
        ),
    ],
)
def test_fixture_sandbox_audit_fails_closed_on_incomplete_kernel_evidence(
    tmp_path: Path,
    raw_transform: object,
    match: str,
) -> None:
    nonce = "b" * 64
    netlog = tmp_path / "chromium-netlog.json"
    netlog.write_text('{"events":[]}\n', encoding="utf-8")
    raw = raw_transform(_valid_seatbelt_raw(nonce))

    with pytest.raises(AuditBundleError, match=match):
        mainline_audit._build_fixture_sandbox_audit(
            base_url="http://127.0.0.1:8820",
            browser_requests=[],
            netlog_path=netlog,
            sandbox_profile=mainline_audit._fixture_sandbox_profile(
                nonce
            ),
            measurement_nonce=nonce,
            seatbelt_raw=raw,
            logger_stderr=b"",
            logger_returncode=0,
            sandbox_process_group_id=4100,
            process_group_quiescent=True,
        )


def test_fixture_sandbox_audit_rejects_unexpected_kernel_egress(
    tmp_path: Path,
) -> None:
    nonce = "c" * 64
    netlog = tmp_path / "chromium-netlog.json"
    netlog.write_text(
        '{"events":[{"params":{"url":"http://127.0.0.1:8820/chat"}}]}\n',
        encoding="utf-8",
    )
    unexpected = _seatbelt_log_event(
        message=(
            "Sandbox: Chromium(4102) deny(1) "
            f"network-outbound remote:*:8443\n{nonce}"
        ),
        process_path="/kernel",
        sender_path=(
            "/System/Library/Extensions/Sandbox.kext/"
            "Contents/MacOS/Sandbox"
        ),
    )

    with pytest.raises(AuditBundleError, match="non-loopback"):
        mainline_audit._build_fixture_sandbox_audit(
            base_url="http://127.0.0.1:8820",
            browser_requests=[],
            netlog_path=netlog,
            sandbox_profile=mainline_audit._fixture_sandbox_profile(
                nonce
            ),
            measurement_nonce=nonce,
            seatbelt_raw=_valid_seatbelt_raw(
                nonce,
                extra_events=(unexpected,),
            ),
            logger_stderr=b"",
            logger_returncode=0,
            sandbox_process_group_id=4100,
            process_group_quiescent=True,
        )


def test_fixture_sandbox_profile_reports_denials_with_unique_nonce() -> None:
    nonce = "d" * 64

    profile = mainline_audit._fixture_sandbox_profile(nonce)

    assert "(with telemetry)" in profile
    assert f'(with message "{nonce}")' in profile
    assert '(remote ip "localhost:*")' in profile


def test_fixture_sandbox_finalizer_publishes_raw_kernel_evidence_once(
    tmp_path: Path,
) -> None:
    nonce = "9" * 64
    output = tmp_path / "fixture-browser-desktop"
    output.mkdir()
    netlog = output / "chromium-netlog.json"
    netlog.write_text(
        '{"events":[{"params":{"url":"http://127.0.0.1:8820/chat"}}]}\n',
        encoding="utf-8",
    )
    for turn_id in FIXTURE_TURN_IDS:
        (output / turn_id).mkdir()
    raw = _valid_seatbelt_raw(nonce)
    child_report = {
        "schema_version": "guide-mainline-contract-browser-audit-v1",
        "trajectory_set": "fixture",
        "viewport": "desktop",
        "passed": True,
        "turn_count": len(FIXTURE_TURN_IDS),
        "invalid_clarification_count": 0,
        "runtime_identity_sha256": "1" * 64,
        "consumed_health_challenge_sha256": "2" * 64,
        "sandbox_root_pid": 4100,
        "browser_requests": [
            {
                "url": "http://127.0.0.1:8820/chat",
                "method": "GET",
                "resource_type": "document",
            }
        ],
        "turns": [
            {"turn_id": turn_id, "directory": turn_id}
            for turn_id in FIXTURE_TURN_IDS
        ],
    }
    profile = mainline_audit._fixture_sandbox_profile(nonce)

    report = mainline_audit._finalize_fixture_sandbox_evidence(
        base_url="http://127.0.0.1:8820",
        output=output,
        child_report=child_report,
        sandbox_profile=profile,
        measurement_nonce=nonce,
        seatbelt_raw=raw,
        logger_stderr=b"",
        logger_returncode=0,
        sandbox_root_pid=4100,
        sandbox_process_group_id=4100,
        process_group_quiescent=True,
    )

    raw_path = output / "seatbelt.raw.ndjson"
    audit_path = output / "sandbox-audit.json"
    summary_path = output / "summary.json"
    requests_path = output / "browser-requests.json"
    assert raw_path.read_bytes() == raw
    assert json.loads(requests_path.read_text(encoding="utf-8")) == (
        child_report["browser_requests"]
    )
    assert report["seatbelt_raw_ndjson_sha256"] == sha256(raw).hexdigest()
    assert report["sandbox_audit_sha256"] == sha256(
        audit_path.read_bytes()
    ).hexdigest()
    assert "browser_requests" not in report
    assert (
        report["artifact_sha256_by_path"]["seatbelt.raw.ndjson"]
        == sha256(raw).hexdigest()
    )
    assert report["artifact_sha256_by_path"][
        "browser-requests.json"
    ] == sha256(requests_path.read_bytes()).hexdigest()
    assert json.loads(summary_path.read_text(encoding="utf-8")) == report
    for turn_id in FIXTURE_TURN_IDS:
        assert (
            (output / turn_id / "sandbox-audit.json").read_bytes()
            == audit_path.read_bytes()
        )

    original_summary = summary_path.read_bytes()
    with pytest.raises(AuditBundleError, match="already exists"):
        mainline_audit._finalize_fixture_sandbox_evidence(
            base_url="http://127.0.0.1:8820",
            output=output,
            child_report=child_report,
            sandbox_profile=profile,
            measurement_nonce=nonce,
            seatbelt_raw=raw,
            logger_stderr=b"",
            logger_returncode=0,
            sandbox_root_pid=4100,
            sandbox_process_group_id=4100,
            process_group_quiescent=True,
        )
    assert summary_path.read_bytes() == original_summary


def test_fixture_sandbox_finalizer_preserves_failed_kernel_evidence(
    tmp_path: Path,
) -> None:
    nonce = "8" * 64
    output = tmp_path / "fixture-browser-desktop"
    output.mkdir()
    (output / "chromium-netlog.json").write_text(
        '{"events":[{"params":{"url":"http://127.0.0.1:8820/chat"}}]}\n',
        encoding="utf-8",
    )
    for turn_id in FIXTURE_TURN_IDS:
        (output / turn_id).mkdir()
    unexpected = _seatbelt_log_event(
        message=(
            "Sandbox: Chromium(4102) deny(1) "
            f"network-outbound remote:*:8443\n{nonce}"
        ),
        process_path="/kernel",
        sender_path=(
            "/System/Library/Extensions/Sandbox.kext/"
            "Contents/MacOS/Sandbox"
        ),
    )
    raw = _valid_seatbelt_raw(
        nonce,
        extra_events=(unexpected,),
    )
    child_report = {
        "schema_version": "guide-mainline-contract-browser-audit-v1",
        "trajectory_set": "fixture",
        "viewport": "desktop",
        "passed": True,
        "turn_count": len(FIXTURE_TURN_IDS),
        "invalid_clarification_count": 0,
        "runtime_identity_sha256": "1" * 64,
        "consumed_health_challenge_sha256": "2" * 64,
        "sandbox_root_pid": 4100,
        "browser_requests": [],
        "turns": [
            {"turn_id": turn_id, "directory": turn_id}
            for turn_id in FIXTURE_TURN_IDS
        ],
    }

    with pytest.raises(AuditBundleError, match="non-loopback"):
        mainline_audit._finalize_fixture_sandbox_evidence(
            base_url="http://127.0.0.1:8820",
            output=output,
            child_report=child_report,
            sandbox_profile=mainline_audit._fixture_sandbox_profile(
                nonce
            ),
            measurement_nonce=nonce,
            seatbelt_raw=raw,
            logger_stderr=b"",
            logger_returncode=0,
            sandbox_root_pid=4100,
            sandbox_process_group_id=4100,
            process_group_quiescent=True,
        )

    assert (output / "seatbelt.raw.ndjson").read_bytes() == raw
    failed_audit = json.loads(
        (output / "sandbox-audit.json").read_text(encoding="utf-8")
    )
    assert failed_audit["passed"] is False
    assert failed_audit["failure_code"] == "non_loopback_attempt"
    failed_summary = json.loads(
        (output / "summary.json").read_text(encoding="utf-8")
    )
    assert failed_summary["passed"] is False
    assert failed_summary["sandbox_audit_sha256"] == sha256(
        (output / "sandbox-audit.json").read_bytes()
    ).hexdigest()


def test_fixture_sandbox_context_binds_nonce_to_effective_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    nonce = "e" * 64
    profile = mainline_audit._fixture_sandbox_profile(nonce)
    profile_sha256 = sha256(profile.encode("utf-8")).hexdigest()
    monkeypatch.setenv(
        mainline_audit._FIXTURE_SANDBOX_NONCE_ENV,
        nonce,
    )
    monkeypatch.setenv(
        mainline_audit._FIXTURE_SANDBOX_ENV,
        profile_sha256,
    )

    context = mainline_audit._fixture_sandbox_context()

    assert context == {
        "measurement_nonce": nonce,
        "sandbox_profile": profile,
        "sandbox_profile_sha256": profile_sha256,
    }
    monkeypatch.setenv(
        mainline_audit._FIXTURE_SANDBOX_ENV,
        "f" * 64,
    )
    assert mainline_audit._fixture_sandbox_context() is None


def test_fixture_sandbox_parent_collects_and_seals_kernel_log(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    nonce = "7" * 64
    output = tmp_path / "fixture-browser-desktop"
    calls: list[tuple[tuple[str, ...], str, str]] = []

    def execute(
        *,
        argv: tuple[str, ...],
        sandbox_profile: str,
        measurement_nonce: str,
        environment: dict[str, str],
    ) -> dict[str, object]:
        calls.append((argv, sandbox_profile, measurement_nonce))
        assert environment[
            mainline_audit._FIXTURE_SANDBOX_NONCE_ENV
        ] == nonce
        output.mkdir()
        (output / "chromium-netlog.json").write_text(
            '{"events":[{"params":{"url":"http://127.0.0.1:8820/chat"}}]}\n',
            encoding="utf-8",
        )
        for turn_id in FIXTURE_TURN_IDS:
            (output / turn_id).mkdir()
        child_report = {
            "schema_version": (
                "guide-mainline-contract-browser-audit-v1"
            ),
            "trajectory_set": "fixture",
            "base_url": "http://127.0.0.1:8820",
            "viewport": "desktop",
            "passed": True,
            "turn_count": len(FIXTURE_TURN_IDS),
            "invalid_clarification_count": 0,
            "runtime_identity_sha256": "1" * 64,
            "consumed_health_challenge_sha256": "2" * 64,
            "sandbox_root_pid": 4100,
            "browser_requests": [],
            "turns": [
                {"turn_id": turn_id, "directory": turn_id}
                for turn_id in FIXTURE_TURN_IDS
            ],
        }
        return {
            "child_returncode": 0,
            "child_stdout": (
                json.dumps(child_report, ensure_ascii=True) + "\n"
            ).encode("utf-8"),
            "child_stderr": b"",
            "seatbelt_raw": _valid_seatbelt_raw(nonce),
            "logger_stderr": b"",
            "logger_returncode": 0,
            "sandbox_root_pid": 4100,
            "sandbox_process_group_id": 4100,
            "process_group_quiescent": True,
        }

    monkeypatch.setattr(
        mainline_audit.secrets,
        "token_hex",
        lambda size: nonce,
    )
    monkeypatch.setattr(
        mainline_audit,
        "_execute_fixture_sandbox_process",
        execute,
        raising=False,
    )

    returncode = mainline_audit._run_fixture_in_macos_sandbox(
        ("--trajectory-set", "fixture"),
        output=output,
    )

    assert returncode == 0
    assert calls == [
        (
            ("--trajectory-set", "fixture"),
            mainline_audit._fixture_sandbox_profile(nonce),
            nonce,
        )
    ]
    summary = json.loads(
        (output / "summary.json").read_text(encoding="utf-8")
    )
    assert summary["passed"] is True
    assert summary["seatbelt_raw_ndjson_sha256"] == sha256(
        _valid_seatbelt_raw(nonce)
    ).hexdigest()


def test_fixture_sandbox_parent_preserves_child_failure_evidence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    nonce = "6" * 64
    output = tmp_path / "fixture-browser-desktop"

    def execute(**_: object) -> dict[str, object]:
        output.mkdir()
        return {
            "child_returncode": 7,
            "child_stdout": b"",
            "child_stderr": b"browser failed\n",
            "seatbelt_raw": _seatbelt_log_event(
                message=f"XIAORO_SEATBELT_READY:{nonce}",
                process_path="/usr/bin/logger",
            ),
            "logger_stderr": b"",
            "logger_returncode": 0,
            "sandbox_root_pid": 4100,
            "sandbox_process_group_id": 4100,
            "process_group_quiescent": True,
        }

    monkeypatch.setattr(
        mainline_audit.secrets,
        "token_hex",
        lambda size: nonce,
    )
    monkeypatch.setattr(
        mainline_audit,
        "_execute_fixture_sandbox_process",
        execute,
    )

    returncode = mainline_audit._run_fixture_in_macos_sandbox(
        ("--trajectory-set", "fixture"),
        output=output,
    )

    assert returncode == 7
    assert (output / "seatbelt.raw.ndjson").is_file()
    audit = json.loads(
        (output / "sandbox-audit.json").read_text(encoding="utf-8")
    )
    assert audit["passed"] is False
    assert audit["failure_code"] == "sandbox_child_failed"
    assert audit["child_returncode"] == 7
    summary = json.loads(
        (output / "summary.json").read_text(encoding="utf-8")
    )
    assert summary["passed"] is False
    assert summary["sandbox_audit_sha256"] == sha256(
        (output / "sandbox-audit.json").read_bytes()
    ).hexdigest()


def test_fixture_sandbox_parent_rejects_non_quiescent_process_group(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    nonce = "5" * 64

    monkeypatch.setattr(
        mainline_audit.secrets,
        "token_hex",
        lambda size: nonce,
    )
    monkeypatch.setattr(
        mainline_audit,
        "_execute_fixture_sandbox_process",
        lambda **_: {
            "child_returncode": 0,
            "child_stdout": b"{}\n",
            "child_stderr": b"",
            "seatbelt_raw": _valid_seatbelt_raw(nonce),
            "logger_stderr": b"",
            "logger_returncode": 0,
            "sandbox_root_pid": 4100,
            "sandbox_process_group_id": 4100,
            "process_group_quiescent": False,
        },
    )

    with pytest.raises(
        AuditBundleError,
        match="execution result is invalid",
    ):
        mainline_audit._run_fixture_in_macos_sandbox(
            ("--trajectory-set", "fixture"),
            output=tmp_path / "fixture-browser-desktop",
        )


def test_fixture_drain_canary_is_parent_marked_before_release(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    writes: list[bytes] = []
    started: list[int] = []

    class _FakeStdin:
        def write(self, value: bytes) -> int:
            writes.append(value)
            return len(value)

        def close(self) -> None:
            return None

    class _FakeProcess:
        pid = 4200
        returncode: int | None = None
        stdin: _FakeStdin | None = _FakeStdin()

        def communicate(
            self,
            *,
            timeout: float,
        ) -> tuple[bytes, bytes]:
            assert timeout == 10
            assert writes == [b"1"]
            self.returncode = 1
            return b"", b""

        def poll(self) -> int | None:
            return self.returncode

    monkeypatch.setattr(
        mainline_audit.subprocess,
        "Popen",
        lambda *args, **kwargs: _FakeProcess(),
    )
    monkeypatch.setattr(
        mainline_audit.os,
        "getpgid",
        lambda pid: pid,
    )
    monkeypatch.setattr(
        mainline_audit,
        "_wait_for_process_group_exit",
        lambda process_group_id: process_group_id == 4200,
    )

    pid = mainline_audit._run_fixture_drain_canary(
        sandbox_profile="profile",
        measurement_nonce="a" * 64,
        environment={},
        on_started=lambda process_id: started.append(process_id),
    )

    assert pid == 4200
    assert started == [4200]
    assert writes == [b"1"]


def test_fixture_drain_canary_kills_nonquiescent_descendants(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    terminated: list[int] = []

    class _FakeStdin:
        def write(self, value: bytes) -> int:
            return len(value)

        def close(self) -> None:
            return None

    class _FakeProcess:
        pid = 4200
        returncode: int | None = None
        stdin: _FakeStdin | None = _FakeStdin()

        def communicate(
            self,
            *,
            timeout: float,
        ) -> tuple[bytes, bytes]:
            self.returncode = 1
            return b"", b""

        def poll(self) -> int | None:
            return self.returncode

    monkeypatch.setattr(
        mainline_audit.subprocess,
        "Popen",
        lambda *args, **kwargs: _FakeProcess(),
    )
    monkeypatch.setattr(
        mainline_audit.os,
        "getpgid",
        lambda pid: pid,
    )
    monkeypatch.setattr(
        mainline_audit,
        "_wait_for_process_group_exit",
        lambda process_group_id: False,
    )
    monkeypatch.setattr(
        mainline_audit,
        "_terminate_fixture_process_group",
        lambda process: terminated.append(process.pid),
    )

    with pytest.raises(AuditBundleError, match="not quiescent"):
        mainline_audit._run_fixture_drain_canary(
            sandbox_profile="profile",
            measurement_nonce="a" * 64,
            environment={},
            on_started=lambda process_id: None,
        )

    assert terminated == [4200]


def test_fixture_drain_child_requires_start_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    nonce = "a" * 64
    calls: list[str] = []
    monkeypatch.setattr(
        mainline_audit,
        "_require_fixture_canary_gate",
        lambda expected, *, stage: calls.append(
            f"gate:{stage}:{expected.decode('ascii')}"
        ),
    )
    monkeypatch.setattr(
        mainline_audit,
        "_run_seatbelt_canary_child",
        lambda measurement_nonce, scope, port: (
            calls.append(
                f"canary:{measurement_nonce}:{scope}:{port}"
            )
            or 1
        ),
    )

    result = mainline_audit.main([
        "--seatbelt-canary-child",
        nonce,
        "drain",
        "53",
    ])

    assert result == 1
    assert calls == [
        "gate:drain:1",
        f"canary:{nonce}:drain:53",
    ]


def test_fixture_capture_waits_for_every_required_marker_family() -> None:
    marker_events = {
        name: threading.Event()
        for name in (
            "begin",
            "root_child",
            "descendant",
            "end",
        )
    }
    marker_events["begin"].set()
    marker_events["root_child"].set()
    marker_events["end"].set()

    delivery = threading.Timer(
        0.05,
        marker_events["descendant"].set,
    )
    delivery.start()
    try:
        mainline_audit._wait_for_fixture_marker_delivery(
            marker_events=marker_events,
            required_markers=tuple(marker_events),
            timeout_seconds=1.0,
        )
    finally:
        delivery.join(timeout=1)


def test_short_lived_fixture_canaries_do_not_emit_logger_markers() -> None:
    child_source = inspect.getsource(
        mainline_audit._run_seatbelt_canary_child
    )
    harness_source = inspect.getsource(
        mainline_audit._run_seatbelt_canaries
    )
    capture_source = inspect.getsource(
        mainline_audit._execute_fixture_sandbox_process
    )

    assert "_emit_seatbelt_marker" not in child_source
    assert "_emit_seatbelt_marker" not in harness_source
    assert "stdin=subprocess.PIPE" in capture_source
    assert 'child.stdin.write(b"1")' in capture_source
    assert 'child.stdin.write(b"2")' in capture_source
    assert capture_source.count("_emit_seatbelt_marker(") >= 6


def test_fixture_cli_runs_seatbelt_canaries_before_runtime_claim(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    nonce = "1" * 64
    profile = mainline_audit._fixture_sandbox_profile(nonce)
    calls: list[str] = []
    monkeypatch.setenv(
        mainline_audit._FIXTURE_SANDBOX_NONCE_ENV,
        nonce,
    )
    monkeypatch.setenv(
        mainline_audit._FIXTURE_SANDBOX_ENV,
        sha256(profile.encode("utf-8")).hexdigest(),
    )
    monkeypatch.setattr(
        mainline_audit,
        "_run_seatbelt_canaries",
        lambda measurement_nonce: (
            calls.append(f"canary:{measurement_nonce}") or 4100
        ),
        raising=False,
    )
    monkeypatch.setattr(
        mainline_audit,
        "_verified_fixture_runtime",
        lambda **_: (
            calls.append("runtime")
            or {
                "runtime_identity_sha256": "2" * 64,
                "consumed_health_challenge_sha256": "3" * 64,
            }
        ),
    )
    monkeypatch.setattr(
        mainline_audit,
        "run_fixture_browser_audits",
        lambda **kwargs: (
            calls.append("browser")
            or {
                "passed": True,
                "sandbox_root_pid": kwargs["sandbox_root_pid"],
            }
        ),
    )
    monkeypatch.setattr(
        mainline_audit,
        "_require_fixture_canary_gate",
        lambda expected, *, stage: calls.append(
            f"gate:{stage}:{expected.decode('ascii')}"
        ),
        raising=False,
    )

    result = mainline_audit.main([
        "--base-url",
        "http://127.0.0.1:8820",
        "--runtime-identity",
        str(tmp_path / "runtime.json"),
        "--expected-manifest-sha256",
        "a" * 64,
        "--trajectory-set",
        "fixture",
        "--viewport",
        "desktop",
        "--output",
        str(tmp_path / "output"),
    ])

    assert result == 0
    assert calls == [
        "gate:start:1",
        f"canary:{nonce}",
        "gate:completion:2",
        "runtime",
        "browser",
    ]


def test_fixture_cli_enters_sandbox_before_runtime_claim(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[tuple[tuple[str, ...], Path]] = []
    monkeypatch.delenv(
        mainline_audit._FIXTURE_SANDBOX_ENV,
        raising=False,
    )
    monkeypatch.setattr(
        mainline_audit,
        "_run_fixture_in_macos_sandbox",
        lambda argv, *, output: (
            calls.append((tuple(argv), output)) or 0
        ),
        raising=False,
    )
    monkeypatch.setattr(
        mainline_audit,
        "_verified_fixture_runtime",
        lambda **_: pytest.fail(
            "runtime must not be claimed outside the sandbox"
        ),
    )
    argv = [
        "--base-url",
        "http://127.0.0.1:8820",
        "--runtime-identity",
        str(tmp_path / "runtime.json"),
        "--expected-manifest-sha256",
        "a" * 64,
        "--trajectory-set",
        "fixture",
        "--viewport",
        "desktop",
        "--output",
        str(tmp_path / "output"),
    ]

    assert mainline_audit.main(argv) == 0
    assert calls == [(tuple(argv), tmp_path / "output")]


def test_live_terminal_wait_passes_capture_count_by_keyword() -> None:
    calls: list[tuple[str, int | None, int]] = []

    class PageProbe:
        def wait_for_function(
            self,
            expression: str,
            *,
            arg: int | None = None,
            timeout: int,
        ) -> None:
            calls.append((expression, arg, timeout))

        def evaluate(self, expression: str) -> object:
            if expression == (
                "() => window.__mainlineAuditCaptureErrors"
            ):
                return []
            if expression == (
                "() => window.__mainlineAuditCaptures.length"
            ):
                return 3
            raise AssertionError(expression)

    mainline_audit._wait_for_live_terminal(
        PageProbe(),
        expected_capture_count=3,
    )

    assert calls == [
        (
            (
                """expected => (
            window.__mainlineAuditCaptures.length >= expected
            && window.__mainlineAuditCaptureErrors.length === 0
            && typeof activeChatRequests !== 'undefined'
            && activeChatRequests.size === 0
        )"""
            ),
            3,
            120_000,
        )
    ]


def test_live_terminal_wait_rejects_duplicate_sse_capture() -> None:
    class PageProbe:
        def wait_for_function(
            self,
            expression: str,
            *,
            arg: int | None = None,
            timeout: int,
        ) -> None:
            del expression, arg, timeout

        def evaluate(self, expression: str) -> object:
            if expression == (
                "() => window.__mainlineAuditCaptureErrors"
            ):
                return []
            if expression == (
                "() => window.__mainlineAuditCaptures.length"
            ):
                return 4
            raise AssertionError(expression)

    with pytest.raises(AuditBundleError, match="capture count"):
        mainline_audit._wait_for_live_terminal(
            PageProbe(),
            expected_capture_count=3,
        )


def test_live_bundle_preserves_typed_error_terminal_and_owner(
    tmp_path: Path,
) -> None:
    raw_stream = (
        b"event: error\n"
        b"data: {\"error\":\"PROVIDER_UNAVAILABLE\"}\n\n"
    )

    class PageProbe:
        def evaluate(self, expression: str, *_: object) -> object:
            if expression.startswith("index =>"):
                return {
                    "method": "POST",
                    "url": "http://127.0.0.1:8821/api/v1/chat/stream",
                    "body": json.dumps({"message": "请求失败"}),
                    "bytes": list(raw_stream),
                    "events": [
                        {
                            "event": "error",
                            "data": {
                                "error": "PROVIDER_UNAVAILABLE",
                            },
                        }
                    ],
                }
            if ".message-wrapper.ai[data-guide-request-id]" in expression:
                return "request-live-001"
            raise AssertionError(expression)

        def screenshot(self, *, path: str, full_page: bool) -> None:
            assert full_page is True
            Path(path).write_bytes(_png_bytes(1440, 1000))

    turn = mainline_audit.BOUNDED_TRAJECTORIES[0].turns[0]
    with pytest.raises(
        mainline_audit.BoundedContractError,
        match="PROVIDER_UNAVAILABLE",
    ) as caught:
        mainline_audit._write_live_turn_bundle(
            page=PageProbe(),
            turn_dir=tmp_path,
            trajectory_id="bounded-text-fit",
            turn=turn,
            viewport="desktop",
            capture_index=0,
            evidence={"console": [], "network": []},
        )

    assert caught.value.owner == "sse_contract"
    assert caught.value.failure_code == "PROVIDER_UNAVAILABLE"
    assert (tmp_path / "stream.sse").read_bytes() == raw_stream
    assert set(REQUIRED_TURN_FILES) <= {
        path.name for path in tmp_path.iterdir()
    }
    assert json.loads(
        (tmp_path / "presentation-contract.json").read_text(
            encoding="utf-8"
        )
    ) == {
        "terminal_kind": "error",
        "error": {
            "error": "PROVIDER_UNAVAILABLE",
        },
    }


def test_live_bundle_persists_raw_sse_after_failed_wrapper_is_removed(
    tmp_path: Path,
) -> None:
    raw_stream = (
        b"event: error\n"
        b"data: {\"error\":\"PROVIDER_UNAVAILABLE\"}\n\n"
    )

    class PageProbe:
        def evaluate(self, expression: str, *_: object) -> object:
            if expression.startswith("index =>"):
                return {
                    "method": "POST",
                    "url": "http://127.0.0.1:8821/api/v1/chat/stream",
                    "body": json.dumps({"message": "请求失败"}),
                    "bytes": list(raw_stream),
                    "events": [
                        {
                            "event": "error",
                            "data": {
                                "error": "PROVIDER_UNAVAILABLE",
                            },
                        }
                    ],
                }
            if ".message-wrapper.ai[data-guide-request-id]" in expression:
                return None
            raise AssertionError(expression)

        def screenshot(self, *, path: str, full_page: bool) -> None:
            assert full_page is True
            Path(path).write_bytes(_png_bytes(1440, 1000))

    turn = mainline_audit.BOUNDED_TRAJECTORIES[0].turns[0]
    with pytest.raises(
        mainline_audit.BoundedContractError,
        match="PROVIDER_UNAVAILABLE",
    ) as caught:
        mainline_audit._write_live_turn_bundle(
            page=PageProbe(),
            turn_dir=tmp_path,
            trajectory_id="bounded-text-fit",
            turn=turn,
            viewport="desktop",
            capture_index=0,
            evidence={"console": [], "network": []},
        )

    assert caught.value.owner == "sse_contract"
    assert caught.value.failure_code == "PROVIDER_UNAVAILABLE"
    assert (tmp_path / "stream.sse").read_bytes() == raw_stream
    request = json.loads(
        (tmp_path / "request.json").read_text(encoding="utf-8")
    )
    assert request["request_id"] is None
    assert json.loads(
        (tmp_path / "presentation-contract.json").read_text(
            encoding="utf-8"
        )
    )["terminal_kind"] == "error"


def test_saved_error_terminal_is_owned_by_sse_contract(
    tmp_path: Path,
) -> None:
    (tmp_path / "presentation-contract.json").write_text(
        json.dumps(
            {
                "terminal_kind": "error",
                "error": {
                    "error": "GUIDE_INTERNAL_ERROR",
                    "message": "推荐暂时不可用，请稍后重试。",
                },
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "terminal-dom.json").write_text(
        "{}\n",
        encoding="utf-8",
    )

    assert (
        mainline_audit._failure_owner_from_bundle(tmp_path)
        == "sse_contract"
    )


def test_live_bundle_writes_typed_clarification_terminal(
    tmp_path: Path,
) -> None:
    clarification = {
        "question": "请补充一个更明确的使用场景。",
        "clarification_code": "goal",
    }
    raw_stream = (
        b"event: start\n"
        b"data: {\"session_id\":\"clarification\"}\n\n"
        b"event: intent\n"
        b"data: {\"intent\":\"clarify\"}\n\n"
        b"event: clarify\n"
        b"data: {\"question\":\""
        b"\xe8\xaf\xb7\xe8\xa1\xa5\xe5\x85\x85\xe4\xb8\x80\xe4\xb8\xaa"
        b"\xe6\x9b\xb4\xe6\x98\x8e\xe7\xa1\xae\xe7\x9a\x84\xe4\xbd\xbf"
        b"\xe7\x94\xa8\xe5\x9c\xba\xe6\x99\xaf\xe3\x80\x82\","
        b"\"clarification_code\":\"goal\"}\n\n"
        b"event: end\n"
        b"data: {\"conversation_version\":1}\n\n"
    )

    class PageProbe:
        def evaluate(self, expression: str, *_: object) -> object:
            if expression.startswith("index =>"):
                return {
                    "method": "POST",
                    "url": "http://127.0.0.1:8821/api/v1/chat/stream",
                    "body": json.dumps({"message": "请求澄清"}),
                    "bytes": list(raw_stream),
                    "events": [
                        {
                            "event": "start",
                            "data": {"session_id": "clarification"},
                        },
                        {
                            "event": "intent",
                            "data": {"intent": "clarify"},
                        },
                        {"event": "clarify", "data": clarification},
                        {
                            "event": "end",
                            "data": {"conversation_version": 1},
                        },
                    ],
                }
            if expression.startswith("input =>"):
                return {
                    "request_id": "request-clarification-001",
                    "terminal_kind": "clarification",
                    "presentation_mode": None,
                    "legacy_message_count": 0,
                    "clarification_message_count": 1,
                    "legacy_product_card_count": 0,
                    "turn_presentation_root_count": 0,
                    "visible_section_kinds": [],
                    "inline_product_ids": [],
                    "visible_product_ids": [],
                    "shelf_product_ids": [],
                    "presentation_text": clarification["question"],
                }
            if ".message-wrapper.ai[data-guide-request-id]" in expression:
                return "request-clarification-001"
            raise AssertionError(expression)

        def screenshot(self, *, path: str, full_page: bool) -> None:
            assert full_page is True
            Path(path).write_bytes(_png_bytes(1440, 1000))

    turn = mainline_audit.BOUNDED_TRAJECTORIES[0].turns[0]
    terminal, observations = mainline_audit._write_live_turn_bundle(
        page=PageProbe(),
        turn_dir=tmp_path,
        trajectory_id="bounded-text-fit",
        turn=turn,
        viewport="desktop",
        capture_index=0,
        evidence={"console": [], "network": []},
    )

    assert terminal == {
        "terminal_kind": "clarification",
        "clarification": clarification,
    }
    assert observations == ()
    validate_audit_bundle(
        tmp_path,
        expected_turn_id="bounded-text-fit-t1",
    )


def test_audit_bundle_requires_same_turn_contract_dom_and_screenshot(
    tmp_path: Path,
) -> None:
    with pytest.raises(
        AuditBundleError,
        match="presentation-contract.json",
    ):
        validate_audit_bundle(
            tmp_path,
            expected_turn_id="text-fit-001",
        )


def test_audit_bundle_accepts_bound_contract_dom_and_screenshot(
    tmp_path: Path,
) -> None:
    request = {
        "turn_id": "text-fit-001",
        "request_id": "request-001",
        "viewport": {"width": 1440, "height": 1000},
    }
    contract = {
        "mode": "recommendation",
        "visible_product_ids": [38],
        "sections": [
            {"kind": "summary", "copy_text": "先看修护路线。"},
            {
                "kind": "product",
                "product_id": 38,
                "copy_text": "品牌主打修护舒缓。",
                "advisor_reason": "更贴合换季泛红。",
                "direct_facts": [
                    {
                        "fact_id": "fact:38:ingredient",
                        "label": "核心成分",
                        "display_value": "维生素原 B5\n（泛醇）",
                    }
                ],
            },
            {"kind": "closing", "copy_text": None},
            {"kind": "full_cards", "copy_text": None},
        ],
    }
    dom = {
        "request_id": "request-001",
        "presentation_mode": "recommendation",
        "legacy_message_count": 0,
        "legacy_product_card_count": 0,
        "turn_presentation_root_count": 1,
        "visible_section_kinds": [
            "summary",
            "product",
            "closing",
            "full_cards",
        ],
        "section_blocks": [
            {"kind": "summary", "text": "先看修护路线。"},
            {
                "kind": "product",
                "text": (
                    "品牌主打修护舒缓。 维生素原 B5 （泛醇） "
                    "更贴合换季泛红。"
                ),
            },
            {"kind": "closing", "text": ""},
            {"kind": "full_cards", "text": "本轮提到的商品"},
        ],
        "inline_product_ids": [38],
        "visible_product_ids": [38],
        "shelf_product_ids": [38],
        "presentation_text": (
            "先看修护路线。 品牌主打修护舒缓。 "
            "更贴合换季泛红。 维生素原 B5 （泛醇）"
        ),
    }
    payloads = {
        "request.json": json.dumps(request),
        "stream.sse": _presentation_stream(
            contract,
            product_ids=(38,),
        ),
        "presentation-contract.json": json.dumps(contract),
        "terminal-dom.json": json.dumps(dom),
        "screenshot.png": _png_bytes(1440, 1000),
        "console.json": "[]",
        "network.json": "[]",
    }
    _write_bundle_payloads(tmp_path, payloads)

    validate_audit_bundle(
        tmp_path,
        expected_turn_id="text-fit-001",
    )

    assert set(REQUIRED_TURN_FILES) == set(payloads)
    assert required_public_text(tuple(contract["sections"])) == (
        "先看修护路线。",
        "品牌主打修护舒缓。",
        "更贴合换季泛红。",
        "维生素原 B5\n（泛醇）",
    )


def test_comparison_bundle_requires_visible_comparison_table(
    tmp_path: Path,
) -> None:
    request = {
        "turn_id": "image-comparison-001",
        "request_id": "request-image-comparison-001",
    }
    contract = {
        "mode": "comparison",
        "visible_product_ids": [38, 91],
        "sections": [{"kind": "comparison"}],
        "comparison_rows": [
            {
                "dimension_id": "brand_main",
                "label": "品牌主打",
                "cells": [],
            }
        ],
    }
    dom = {
        "request_id": "request-image-comparison-001",
        "presentation_mode": "comparison",
        "legacy_message_count": 0,
        "legacy_product_card_count": 0,
        "turn_presentation_root_count": 1,
        "visible_section_kinds": ["comparison"],
        "section_blocks": [
            {"kind": "comparison", "text": ""},
        ],
        "inline_product_ids": [],
        "visible_product_ids": [38, 91],
        "shelf_product_ids": [38, 91],
        "comparison_table_count": 0,
        "presentation_text": "",
    }
    payloads = {
        "request.json": json.dumps(request),
        "stream.sse": _presentation_stream(
            contract,
            product_ids=(38, 91),
        ),
        "presentation-contract.json": json.dumps(contract),
        "terminal-dom.json": json.dumps(dom),
        "screenshot.png": _png_bytes(8, 5),
        "console.json": "[]",
        "network.json": "[]",
    }
    _write_bundle_payloads(tmp_path, payloads)

    with pytest.raises(
        AuditBundleError,
        match="comparison table count mismatch",
    ):
        validate_audit_bundle(
            tmp_path,
            expected_turn_id="image-comparison-001",
        )


def test_demo_usefulness_rejects_all_unknown_generic_comparison() -> None:
    contract = {
        "responsibility": "comparison",
        "mode": "comparison",
        "requested_comparison_dimensions": [],
        "visible_product_ids": [38, 91],
        "comparison_rows": [
            {
                "dimension_id": dimension_id,
                "cells": [
                    {
                        "product_id": product_id,
                        "value": "尚未确认",
                        "fact_ids": [],
                        "state": "unknown",
                    }
                    for product_id in (38, 91)
                ],
            }
            for dimension_id in ("brand_main", "profile_match")
        ],
        "sections": [{"kind": "comparison"}],
    }

    with pytest.raises(
        AuditBundleError,
        match="comparison has no useful dimensions",
    ):
        mainline_audit._validate_demo_usefulness(
            contract=contract,
            events=(),
        )


def test_demo_usefulness_accepts_fact_backed_generic_comparison() -> None:
    contract = {
        "responsibility": "comparison",
        "mode": "comparison",
        "requested_comparison_dimensions": [],
        "visible_product_ids": [38, 91],
        "comparison_rows": [
            {
                "dimension_id": dimension_id,
                "cells": [
                    {
                        "product_id": product_id,
                        "value": value,
                        "fact_ids": [
                            f"fact:{product_id}:{dimension_id}"
                        ],
                        "state": "known",
                    }
                    for product_id, value in (
                        (38, first),
                        (91, second),
                    )
                ],
            }
            for dimension_id, first, second in (
                ("efficacy", "修护", "保湿"),
                ("reference_price", "¥249", "¥88"),
            )
        ],
        "sections": [{"kind": "comparison"}],
    }

    mainline_audit._validate_demo_usefulness(
        contract=contract,
        events=(),
    )


def test_demo_usefulness_rejects_recommendation_without_fact_reason() -> None:
    contract = {
        "responsibility": "recommendation",
        "mode": "recommendation",
        "visible_product_ids": [38],
        "comparison_rows": [],
        "sections": [
            {"kind": "summary", "copy_text": "给你一款。"},
            {
                "kind": "product",
                "product_id": 38,
                "copy_text": "可以看看。",
                "used_fact_ids": [],
                "advisor_used_fact_ids": [],
                "direct_facts": [],
            },
            {"kind": "full_cards"},
        ],
    }

    with pytest.raises(
        AuditBundleError,
        match="recommendation product has no fact-backed reason",
    ):
        mainline_audit._validate_demo_usefulness(
            contract=contract,
            events=(),
        )


def test_demo_usefulness_rejects_empty_product_knowledge() -> None:
    contract = {
        "responsibility": "product_knowledge",
        "mode": "product_knowledge",
        "visible_product_ids": [38],
        "comparison_rows": [],
        "sections": [
            {"kind": "summary", "copy_text": "我整理了商品信息。"},
            {
                "kind": "answer",
                "copy_text": None,
                "used_fact_ids": [],
                "direct_facts": [],
            },
            {"kind": "full_cards"},
        ],
    }

    with pytest.raises(
        AuditBundleError,
        match="product knowledge answer is empty",
    ):
        mainline_audit._validate_demo_usefulness(
            contract=contract,
            events=(),
        )


def test_demo_usefulness_rejects_ungrounded_product_knowledge() -> None:
    contract = {
        "responsibility": "product_knowledge",
        "mode": "product_knowledge",
        "visible_product_ids": [38],
        "comparison_rows": [],
        "sections": [
            {"kind": "summary", "copy_text": "我整理了商品信息。"},
            {
                "kind": "answer",
                "copy_text": "这款应该挺好用。",
                "used_fact_ids": [],
                "direct_facts": [],
            },
            {"kind": "full_cards"},
        ],
    }

    with pytest.raises(
        AuditBundleError,
        match="product knowledge answer is not evidence-backed",
    ):
        mainline_audit._validate_demo_usefulness(
            contract=contract,
            events=(),
        )


def test_demo_usefulness_accepts_precise_product_evidence_gap() -> None:
    contract = {
        "responsibility": "product_knowledge",
        "mode": "product_knowledge",
        "visible_product_ids": [38],
        "comparison_rows": [],
        "sections": [
            {"kind": "summary", "copy_text": "我整理了商品信息。"},
            {
                "kind": "answer",
                "copy_text": "这款目前没有明确标注的质地信息。",
                "used_fact_ids": [],
                "direct_facts": [],
            },
            {"kind": "full_cards"},
        ],
    }

    mainline_audit._validate_demo_usefulness(
        contract=contract,
        events=(),
    )


def test_demo_usefulness_defers_typed_clarification_validation() -> None:
    mainline_audit._validate_demo_usefulness(
        contract={
            "terminal_kind": "clarification",
            "clarification": {
                "question": "请补充一个更明确的功效方向。",
            },
        },
        events=(),
    )


def test_audit_bundle_accepts_shelf_only_product_knowledge(
    tmp_path: Path,
) -> None:
    request = {
        "turn_id": "knowledge-001",
        "request_id": "request-knowledge-001",
    }
    contract = {
        "mode": "product_knowledge",
        "visible_product_ids": [38],
        "sections": [
            {"kind": "summary", "copy_text": "先确认这款精华。"},
            {
                "kind": "answer",
                "copy_text": "品牌主打修护舒缓。",
            },
            {"kind": "full_cards", "copy_text": None},
        ],
    }
    dom = {
        "request_id": "request-knowledge-001",
        "presentation_mode": "product_knowledge",
        "legacy_message_count": 0,
        "legacy_product_card_count": 0,
        "turn_presentation_root_count": 1,
        "visible_section_kinds": ["summary", "answer", "full_cards"],
        "section_blocks": [
            {"kind": "summary", "text": "先确认这款精华。"},
            {"kind": "answer", "text": "品牌主打修护舒缓。"},
            {"kind": "full_cards", "text": "本轮提到的商品"},
        ],
        "inline_product_ids": [],
        "visible_product_ids": [38],
        "shelf_product_ids": [38],
        "presentation_text": "先确认这款精华。 品牌主打修护舒缓。",
    }
    payloads = {
        "request.json": json.dumps(request),
        "stream.sse": _presentation_stream(
            contract,
            product_ids=(38,),
        ),
        "presentation-contract.json": json.dumps(contract),
        "terminal-dom.json": json.dumps(dom),
        "screenshot.png": _png_bytes(8, 5),
        "console.json": "[]",
        "network.json": "[]",
    }
    _write_bundle_payloads(tmp_path, payloads)

    validate_audit_bundle(
        tmp_path,
        expected_turn_id="knowledge-001",
    )


def test_audit_bundle_accepts_typed_terminal_clarification(
    tmp_path: Path,
) -> None:
    request = {
        "turn_id": "fit-clarification-001",
        "request_id": "request-clarification-001",
    }
    terminal = {
        "terminal_kind": "clarification",
        "clarification": {
            "question": "请补充一个更明确的使用场景。",
            "clarification_code": "goal",
        },
    }
    dom = {
        "request_id": "request-clarification-001",
        "terminal_kind": "clarification",
        "presentation_mode": None,
        "legacy_message_count": 0,
        "clarification_message_count": 1,
        "legacy_product_card_count": 0,
        "turn_presentation_root_count": 0,
        "visible_section_kinds": [],
        "inline_product_ids": [],
        "visible_product_ids": [],
        "shelf_product_ids": [],
        "presentation_text": "请补充一个更明确的使用场景。",
    }
    payloads = {
        "request.json": json.dumps(request),
        "stream.sse": (
            "event: start\n"
            "data: {\"session_id\":\"clarification\"}\n\n"
            "event: intent\n"
            "data: {\"intent\":\"recommend\"}\n\n"
            "event: clarify\n"
            "data: {\"question\":\"请补充一个更明确的使用场景。\","
            "\"clarification_code\":\"goal\"}\n\n"
            "event: end\n"
            "data: {\"conversation_version\":1}\n\n"
        ),
        "presentation-contract.json": json.dumps(terminal),
        "terminal-dom.json": json.dumps(dom),
        "screenshot.png": _png_bytes(8, 5),
        "console.json": "[]",
        "network.json": "[]",
    }
    _write_bundle_payloads(tmp_path, payloads)

    validate_audit_bundle(
        tmp_path,
        expected_turn_id="fit-clarification-001",
    )


def test_audit_bundle_rejects_inline_card_outside_product_section(
    tmp_path: Path,
) -> None:
    request = {
        "turn_id": "knowledge-002",
        "request_id": "request-knowledge-002",
    }
    contract = {
        "mode": "product_knowledge",
        "visible_product_ids": [38],
        "sections": [
            {"kind": "answer", "copy_text": "品牌主打修护舒缓。"},
            {"kind": "full_cards", "copy_text": None},
        ],
    }
    dom = {
        "request_id": "request-knowledge-002",
        "presentation_mode": "product_knowledge",
        "legacy_message_count": 0,
        "legacy_product_card_count": 0,
        "turn_presentation_root_count": 1,
        "visible_section_kinds": ["answer", "full_cards"],
        "section_blocks": [
            {"kind": "answer", "text": "品牌主打修护舒缓。"},
            {"kind": "full_cards", "text": "本轮提到的商品"},
        ],
        "inline_product_ids": [38],
        "visible_product_ids": [38],
        "shelf_product_ids": [38],
        "presentation_text": "品牌主打修护舒缓。",
    }
    payloads = {
        "request.json": json.dumps(request),
        "stream.sse": _presentation_stream(contract),
        "presentation-contract.json": json.dumps(contract),
        "terminal-dom.json": json.dumps(dom),
        "screenshot.png": _png_bytes(8, 5),
        "console.json": "[]",
        "network.json": "[]",
    }
    _write_bundle_payloads(tmp_path, payloads)

    with pytest.raises(
        AuditBundleError,
        match="DOM inline product IDs mismatch",
    ):
        validate_audit_bundle(
            tmp_path,
            expected_turn_id="knowledge-002",
        )


def test_audit_bundle_rejects_copy_rendered_in_wrong_section(
    tmp_path: Path,
) -> None:
    request = {
        "turn_id": "block-owner-001",
        "request_id": "request-block-owner-001",
    }
    contract = {
        "mode": "recommendation",
        "visible_product_ids": [38],
        "sections": [
            {"kind": "summary", "copy_text": "先看修护路线。"},
            {
                "kind": "product",
                "product_id": 38,
                "copy_text": "品牌主打修护舒缓。",
                "advisor_reason": "更贴合当前肤况。",
                "direct_facts": [],
            },
            {"kind": "full_cards", "copy_text": None},
        ],
    }
    dom = {
        "request_id": "request-block-owner-001",
        "presentation_mode": "recommendation",
        "legacy_message_count": 0,
        "legacy_product_card_count": 0,
        "turn_presentation_root_count": 1,
        "visible_section_kinds": [
            "summary",
            "product",
            "full_cards",
        ],
        "section_blocks": [
            {
                "kind": "summary",
                "text": "先看修护路线。 品牌主打修护舒缓。",
            },
            {
                "kind": "product",
                "text": "理肤泉新B5多效修护精华 更贴合当前肤况。",
            },
            {"kind": "full_cards", "text": "本轮提到的商品"},
        ],
        "inline_product_ids": [38],
        "visible_product_ids": [38],
        "shelf_product_ids": [38],
        "presentation_text": (
            "先看修护路线。 品牌主打修护舒缓。 "
            "理肤泉新B5多效修护精华 更贴合当前肤况。"
        ),
    }
    payloads = {
        "request.json": json.dumps(request),
        "stream.sse": _presentation_stream(contract),
        "presentation-contract.json": json.dumps(contract),
        "terminal-dom.json": json.dumps(dom),
        "screenshot.png": _png_bytes(8, 5),
        "console.json": "[]",
        "network.json": "[]",
    }
    _write_bundle_payloads(tmp_path, payloads)

    with pytest.raises(
        AuditBundleError,
        match="DOM section text mismatch",
    ):
        validate_audit_bundle(
            tmp_path,
            expected_turn_id="block-owner-001",
        )


def test_section_block_allows_required_fact_text_in_product_metadata() -> None:
    mainline_audit._validate_section_blocks(
        sections=(
            {
                "kind": "product",
                "copy_text": "这款防晒适合海边使用。",
                "direct_facts": [
                    {
                        "fact_id": "fact:52:efficacy",
                        "label": "功效方向",
                        "display_value": "防晒",
                    }
                ],
                "advisor_reason": "按防晒需求选择。",
            },
        ),
        section_blocks=[
            {
                "kind": "product",
                "text": (
                    "兰蔻防晒隔离乳\n"
                    "这款防晒适合海边使用。\n"
                    "功效方向\n防晒\n"
                    "按防晒需求选择。"
                ),
            }
        ],
    )


def test_audit_bundle_rejects_dom_contract_drift(
    tmp_path: Path,
) -> None:
    for name in REQUIRED_TURN_FILES:
        (tmp_path / name).write_bytes(
            _png_bytes(8, 5)
            if name == "screenshot.png"
            else b"[]"
        )
    (tmp_path / "request.json").write_text(
        json.dumps(
            {
                "turn_id": "comparison-001",
                "request_id": "request-001",
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "presentation-contract.json").write_text(
        json.dumps(
            {
                "mode": "comparison",
                "visible_product_ids": [38, 91],
                "sections": [{"kind": "comparison"}],
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "terminal-dom.json").write_text(
        json.dumps(
            {
                "request_id": "request-002",
                "presentation_mode": "recommendation",
                "legacy_message_count": 0,
                "legacy_product_card_count": 0,
                "turn_presentation_root_count": 1,
                "visible_section_kinds": ["summary"],
                "visible_product_ids": [38],
                "shelf_product_ids": [38],
                "presentation_text": "",
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(AuditBundleError, match="DOM request ID mismatch"):
        validate_audit_bundle(
            tmp_path,
            expected_turn_id="comparison-001",
        )
