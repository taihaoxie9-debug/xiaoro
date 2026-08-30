from __future__ import annotations

import asyncio
from copy import deepcopy
import hashlib
import json
import multiprocessing
import os
import sqlite3
import stat
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.guide.adapters.state.in_memory_image_bundle_state import (
    InMemoryImageBundleState,
)
from app.guide.adapters.catalog import CanonicalProductReader
from app.guide.adapters.catalog.seed_product_assets import (
    load_seed_product_assets,
)
from app.guide.application.image_bundle_service import ImageBundleService
from app.guide.application.execution_contracts import encode_sse_frame
from app.guide.feedback.delivery import FeedbackTargetReceipt
from app.guide.feedback.profile_contracts import ProfileOwnerRef
from app.guide.intent.responsibility_matrix import Responsibility
from app.guide.presentation.sse_events import (
    ClarifyData,
    ClarifyEvent,
    EndData,
    EndEvent,
    ErrorData,
    ErrorEvent,
    IntentData,
    IntentEvent,
    MessageData,
    MessageEvent,
    StartData,
    StartEvent,
)
from app.guide_runtime.app import create_app
from app.guide_runtime.composition import (
    REPO_ROOT,
    build_image_bundle_service,
    guide_image_runtime_lock,
)
from app.guide_runtime.contracts import ChatStreamRequest
from app.guide.understanding.semantic_contracts import ClarificationCode
from tests.guide.semantic_test_port import (
    exact_echo_understanding,
)


MULTITURN_CASES = (
    ("第二款呢", [91], "product_knowledge", 2),
    ("哪个更便宜", [38, 91], "comparison", 2),
    ("预算降到100元呢", [91], "recommendation", 2),
)
SKIN_REVISION_CASES = (
    (
        "改成敏感肌呢",
        [38, 91],
        "INSUFFICIENT_FOR_WINNER",
        2,
    ),
)
IMAGE_UPLOAD_COUNTS = (1, 4)


def test_empty_image_request_requires_typed_action_and_bundle() -> None:
    request = ChatStreamRequest(
        message="",
        image_action="identify",
        session_id="typed-image-action",
        image_bundle_id="bundle_" + "a" * 32,
        image_bundle_version=1,
        image_bundle_token="owner_" + "b" * 43,
    )

    assert request.message == ""
    assert request.image_action == "identify"
    with pytest.raises(
        ValueError,
        match="empty message requires typed image action",
    ):
        ChatStreamRequest(message="")
    with pytest.raises(
        ValueError,
        match="image action requires image bundle",
    ):
        ChatStreamRequest(
            message="",
            image_action="identify",
        )
    with pytest.raises(
        ValueError,
        match="image action forbids message",
    ):
        ChatStreamRequest(
            message="识别这张图",
            image_action="identify",
            image_bundle_id="bundle_" + "a" * 32,
            image_bundle_version=1,
            image_bundle_token="owner_" + "b" * 43,
        )
    with pytest.raises(ValueError, match="Extra inputs are not permitted"):
        ChatStreamRequest(
            message="推荐防晒",
            image_results=[{"product_id": 53}],
        )


@pytest.fixture(autouse=True)
def _isolate_guide_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "XIAORO_GUIDE_STATE_DIR",
        str(tmp_path / "guide-state"),
    )
    from app.guide_runtime import app as app_module
    from app.guide_runtime import composition

    real_build_consultation = (
        composition.build_consultation_vertical_runtime
    )
    from tests.guide.runtime.test_composition import (
        StoredVectorEncoder,
    )
    monkeypatch.setattr(
        composition,
        "_build_runtime_image_encoder",
        lambda **_: StoredVectorEncoder(53),
    )

    def build_consultation(*args, **kwargs):
        kwargs.setdefault(
            "semantic_intent",
            exact_echo_understanding(),
        )
        return real_build_consultation(*args, **kwargs)

    monkeypatch.setattr(
        composition,
        "build_consultation_vertical_runtime",
        build_consultation,
    )
    monkeypatch.setattr(
        app_module,
        "build_consultation_vertical_runtime",
        build_consultation,
    )


def _events(response) -> list[tuple[str, dict]]:
    text = (
        response.text.decode("utf-8")
        if isinstance(response.text, bytes)
        else response.text
    )
    blocks = [
        block
        for block in text.split("\n\n")
        if block.strip()
    ]
    parsed: list[tuple[str, dict]] = []
    for block in blocks:
        name = ""
        payload = ""
        for line in block.splitlines():
            if line.startswith("event: "):
                name = line.removeprefix("event: ").strip()
            elif line.startswith("data: "):
                payload += line.removeprefix("data: ")
        parsed.append((name, json.loads(payload)))
    return parsed


def _jpeg() -> bytes:
    image = Image.new("RGB", (4, 3), color=(23, 67, 101))
    output = BytesIO()
    image.save(output, format="JPEG")
    image.close()
    return output.getvalue()


def _upload_bundle(
    client: TestClient,
    *,
    session_id: str,
    count: int = 1,
) -> dict[str, Any]:
    content = _jpeg()
    response = client.post(
        "/api/v1/chat/image-bundles",
        data={"session_id": session_id},
        files=[
            (
                "images",
                (f"product-{index}.jpg", content, "image/jpeg"),
            )
            for index in range(count)
        ],
    )
    assert response.status_code == 201, response.text
    return response.json()


def _multiprocess_runtime_upload(
    state_directory: str,
    result_queue,
) -> None:
    os.environ["XIAORO_GUIDE_STATE_DIR"] = state_directory
    client = TestClient(create_app())
    result_queue.put(
        _upload_bundle(
            client,
            session_id="multiprocess-image-owner",
        )
    )


def _multiprocess_runtime_authorize(
    state_directory: str,
    receipt: dict[str, Any],
    conversation_version: int,
    result_queue,
) -> None:
    from app.guide_runtime.feedback_http import FEEDBACK_SESSION_COOKIE

    os.environ["XIAORO_GUIDE_STATE_DIR"] = state_directory
    service = build_image_bundle_service()
    runtime = _image_guide_runtime(service)
    client = TestClient(
        create_app(
            consultation_runtime=runtime,
            image_bundle_service=service,
        )
    )
    client.cookies.set(
        FEEDBACK_SESSION_COOKIE,
        "feedback_session_" + "a" * 43,
    )
    response = client.post(
        "/api/v1/chat/stream",
        json={
            "message": "",
            "image_action": "identify",
            "session_id": "multiprocess-image-owner",
            "conversation_version": conversation_version,
            "image_bundle_id": receipt["bundle_id"],
            "image_bundle_version": receipt["version"],
            "image_bundle_token": receipt["owner_token"],
        },
    )
    result_queue.put(_events(response))


def _multiprocess_runtime_delete(
    state_directory: str,
    receipt: dict[str, Any],
    result_queue,
) -> None:
    os.environ["XIAORO_GUIDE_STATE_DIR"] = state_directory
    response = TestClient(create_app()).request(
        "DELETE",
        f"/api/v1/chat/image-bundles/{receipt['bundle_id']}",
        json={
            "session_id": "multiprocess-image-owner",
            "version": receipt["version"],
            "owner_token": receipt["owner_token"],
        },
    )
    result_queue.put(response.status_code)


def _multiprocess_bundle_cas(
    state_directory: str,
    bundle_id: str,
    start_event,
    result_queue,
) -> None:
    os.environ["XIAORO_GUIDE_STATE_DIR"] = state_directory
    service = build_image_bundle_service()
    state = service._state
    bundle = state.load(bundle_id)
    result_queue.put(("ready", bundle is not None))
    start_event.wait(timeout=10)
    if bundle is None:
        result_queue.put(("result", "missing"))
        return
    replacement = bundle.model_copy(
        update={"version": bundle.version + 1},
        deep=True,
    )
    try:
        state.save(replacement, expected_version=bundle.version)
    except Exception as error:
        result_queue.put(("result", type(error).__name__))
    else:
        result_queue.put(("result", "saved"))


def _clarification_events(turn):
    yield encode_sse_frame(
        "start",
        {"session_id": turn.session_id},
    )
    yield encode_sse_frame(
        "intent",
        {
            "intent": "clarify",
            "entities": {},
            "scenario_intent": "clarify",
            "guide": True,
        },
    )
    yield encode_sse_frame(
        "clarify",
        {
            "question": "请补充筛选条件。",
            "clarification_code": "concern",
        },
    )
    yield encode_sse_frame(
        "end",
        {"conversation_version": turn.conversation_version},
    )


class RecordingUnifiedIngress:
    def __init__(self) -> None:
        self.text_calls = []
        self.image_calls = []

    def stream(self, turn):
        self.text_calls.append(turn)
        yield from _clarification_events(turn)

    def stream_image(self, turn):
        self.image_calls.append(turn)
        yield from _clarification_events(turn)


def _runtime_owner() -> ProfileOwnerRef:
    return ProfileOwnerRef(
        scope="anonymous_browser",
        subject_id="runtime_unified_ingress_owner_0123456789",
    )


class _PreparedRecordingFeedback:
    def __init__(self) -> None:
        self.completions = []
        self.persisted = []

    def prepare_completed(self, *, actor, completion):
        del actor
        self.completions.append(completion)
        return SimpleNamespace(
            receipt=FeedbackTargetReceipt(
                conversation_version=completion.conversation_version,
                displayed_product_ids=tuple(
                    completion.card_display.visible_product_ids
                ),
                profile_version=None,
            )
        )

    def persist_prepared(self, prepared):
        self.persisted.append(prepared)
        return prepared.receipt

    def register_completed(self, *, actor, completion):
        prepared = self.prepare_completed(
            actor=actor,
            completion=completion,
        )
        return self.persist_prepared(prepared)


async def _drive_asgi_terminal_delivery(
    response,
    *,
    spec_version: str,
    outcome: str,
    assert_before_terminal_delivery,
    assert_committed,
) -> list[dict[str, Any]]:
    terminal_entered = asyncio.Event()
    release_terminal = asyncio.Event()
    eof_entered = asyncio.Event()
    release_eof = asyncio.Event()
    allow_disconnect = asyncio.Event()
    never_disconnect = asyncio.Event()
    sent: list[dict[str, Any]] = []

    async def receive() -> dict[str, str]:
        if outcome == "disconnect":
            await allow_disconnect.wait()
            return {"type": "http.disconnect"}
        await never_disconnect.wait()
        raise AssertionError("unreachable")

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)
        if message["type"] != "http.response.body":
            return
        body = bytes(message.get("body", b""))
        if b"event: end\n" in body:
            terminal_entered.set()
            await release_terminal.wait()
            if outcome == "send_error":
                raise OSError("terminal transport failed")
        if message.get("more_body") is False:
            eof_entered.set()
            await release_eof.wait()

    async def invoke() -> None:
        await response(
            {
                "type": "http",
                "asgi": {
                    "version": "3.0",
                    "spec_version": spec_version,
                },
            },
            receive,
            send,
        )

    task = asyncio.create_task(invoke())
    await asyncio.wait_for(terminal_entered.wait(), timeout=10)
    terminal = next(
        bytes(message.get("body", b""))
        for message in sent
        if message["type"] == "http.response.body"
        and b"event: end\n" in bytes(message.get("body", b""))
    )
    assert_before_terminal_delivery()
    assert b"event: feedback_target\n" not in terminal

    if outcome == "send_error":
        release_terminal.set()
        result = await asyncio.gather(task, return_exceptions=True)
        assert isinstance(result[0], BaseException)
        assert_before_terminal_delivery()
        return sent
    if outcome == "disconnect":
        allow_disconnect.set()
        await asyncio.wait_for(task, timeout=10)
        assert_before_terminal_delivery()
        return sent

    release_terminal.set()
    await asyncio.wait_for(eof_entered.wait(), timeout=10)
    assert_committed()
    release_eof.set()
    await asyncio.wait_for(task, timeout=10)
    assert_committed()
    return sent


def _image_guide_runtime(
    service: ImageBundleService,
    *,
    product_ids: tuple[int, ...] = (53,),
) -> object:
    from tests.guide.runtime.test_composition import StoredVectorEncoder

    return _build_with_image_encoder(
        StoredVectorEncoder(product_ids),
        semantic_intent=exact_echo_understanding(),
        image_bundle_service=service,
    )


def _build_with_image_encoder(encoder, **kwargs):
    from app.guide_runtime import composition

    with patch.object(
        composition,
        "_build_runtime_image_encoder",
        return_value=encoder,
    ):
        return composition.build_consultation_vertical_runtime(**kwargs)


def _image_client(
    *,
    product_ids: tuple[int, ...] = (53,),
) -> TestClient:
    service = ImageBundleService(
        state=InMemoryImageBundleState(max_bundles=32)
    )
    runtime = _image_guide_runtime(
        service,
        product_ids=product_ids,
    )
    return TestClient(
        create_app(
            consultation_runtime=runtime,
            image_bundle_service=service,
        )
    )


def test_runtime_empty_single_image_uses_typed_identity_action() -> None:
    client = _image_client()
    session_id = "runtime-typed-image-action"
    receipt = _upload_bundle(client, session_id=session_id)

    response = client.post(
        "/api/v1/chat/stream",
        json={
            "message": "",
            "image_action": "identify",
            "session_id": session_id,
            "conversation_version": 0,
            "image_bundle_id": receipt["bundle_id"],
            "image_bundle_version": receipt["version"],
            "image_bundle_token": receipt["owner_token"],
        },
    )

    assert response.status_code == 200
    events = _events(response)
    assert next(
        data["intent"]
        for name, data in events
        if name == "intent"
    ) == "image_identity"
    assert next(
        data["mode"]
        for name, data in events
        if name == "presentation_contract"
    ) == "image_identity"


@pytest.mark.parametrize(
    "product_ids",
    ((53, 55), (53, 55, 57)),
)
def test_runtime_empty_multi_image_uses_typed_compare_action(
    product_ids: tuple[int, ...],
) -> None:
    client = _image_client(product_ids=product_ids)
    session_id = "runtime-typed-image-compare"
    receipt = _upload_bundle(
        client,
        session_id=session_id,
        count=len(product_ids),
    )

    response = client.post(
        "/api/v1/chat/stream",
        json={
            "message": "",
            "image_action": "compare",
            "session_id": session_id,
            "conversation_version": 0,
            "image_bundle_id": receipt["bundle_id"],
            "image_bundle_version": receipt["version"],
            "image_bundle_token": receipt["owner_token"],
        },
    )

    assert response.status_code == 200
    events = _events(response)
    assert next(
        data["intent"]
        for name, data in events
        if name == "intent"
    ) == "image_compare"
    presentation = next(
        data
        for name, data in events
        if name == "presentation_contract"
    )
    assert presentation["mode"] == "comparison"
    assert presentation["visible_product_ids"] == list(product_ids)


def test_runtime_four_image_compare_reaches_image_comparison() -> None:
    client = _image_client(product_ids=(53, 55, 57, 58))
    session_id = "runtime-typed-four-image-compare"
    receipt = _upload_bundle(
        client,
        session_id=session_id,
        count=4,
    )

    response = client.post(
        "/api/v1/chat/stream",
        json={
            "message": "",
            "image_action": "compare",
            "session_id": session_id,
            "conversation_version": 0,
            "image_bundle_id": receipt["bundle_id"],
            "image_bundle_version": receipt["version"],
            "image_bundle_token": receipt["owner_token"],
        },
    )

    assert response.status_code == 200
    events = _events(response)
    names = [name for name, _ in events]
    intent = next(
        data for name, data in events if name == "intent"
    )
    presentation = next(
        data
        for name, data in events
        if name == "presentation_contract"
    )

    assert names.count("image_observation") == 4
    assert intent["intent"] == "image_compare"
    assert presentation["mode"] == "comparison"
    assert presentation["visible_product_ids"] == [53, 55, 57, 58]
    assert names.count("products") == 1
    assert "clarify" not in names
    assert "error" not in names
    assert events[-1] == ("end", {"conversation_version": 1})


def test_health_and_page_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(
        "GUIDE_UNIFIED_ROUTER_ENABLED",
        raising=False,
    )
    client = TestClient(create_app())
    conversation_database = (
        tmp_path / "guide-state" / "conversations.sqlite3"
    )

    health = client.get("/health")
    assert health.status_code == 200
    assert health.json() == {
        "status": "healthy",
        "runtime": "guide",
        "scope": "slice1_text_skincare",
        "turn_router": "unified_v1",
        "capabilities": [
            "sunscreen",
            "repair_serum",
            "scenario_guidance",
            "recent_candidate_followup",
            "budget_revision_followup",
            "skin_revision_followup",
            "secure_image_bundle_input",
            "single_image_similarity",
            "single_image_suitability",
            "two_image_comparison",
            "multi_image_comparison",
            "rapidocr_observation",
            "light_consultation",
            "confirmed_profile_fill",
            "trusted_feedback",
        ],
        "conversation_state": "sqlite_cas",
        "conversation_state_path": {
            "database": "conversations.sqlite3",
            "sha256": hashlib.sha256(
                os.fsencode(conversation_database)
            ).hexdigest(),
        },
        "consultation_state": "sqlite_cas",
        "profile_state": "session_only_conversation_cas",
        "image_runtime": "healthy",
        "image_model": guide_image_runtime_lock().model_name,
        "image_preprocessing_version": (
            guide_image_runtime_lock().preprocessing_version
        ),
        "image_index_sha256": guide_image_runtime_lock().index_sha256,
    }
    assert str(conversation_database.parent) not in health.text

    root = client.get("/", follow_redirects=False)
    assert root.status_code == 307
    assert root.headers["location"] == "/chat"

    chat = client.get("/chat")
    assert chat.status_code == 200
    assert "小 ro 导购" in chat.text
    assert "slice1_text_skincare" in chat.text
    assert "单图识别/适配" in chat.text
    assert "2–3 图比较" in chat.text
    for prohibited in (
        "图片识别",
        "识别图片里的品牌",
        "识别品牌、品类",
        "图片没有识别到清晰的品牌",
        "我没有识别到清晰的品牌",
        "识别到商品：",
        "已识别图片内容",
        "识别图片内容",
        "识别分数约",
        "重新识别",
        "OCR识别结果",
    ):
        assert prohibited not in chat.text
    assert "no-store" in chat.headers["cache-control"]


def test_demo_page_is_isolated_from_acceptance_runtime() -> None:
    client = TestClient(create_app())

    response = client.get("/demo")

    assert response.status_code == 200
    assert "<title>小 Ro 导购 Demo</title>" in response.text
    assert 'class="demo-shell"' in response.text
    assert "slice1_text_skincare" not in response.text
    assert "/api/v1/chat/stream" not in response.text
    assert "no-store" in response.headers["cache-control"]


def test_demo_page_uses_valid_scripted_presentation_contracts() -> None:
    client = TestClient(create_app())

    html = client.get("/demo").text

    assert html.count("recommendation_mode: 'explore'") >= 3
    assert "price_specification_alignment === 'aligned'" in html
    assert "readonly" in html
    assert "const inputText = turn?.question || '';" in html
    assert "P.renderPresentation(output, turn.state, helpers);" in html
    assert "finally {" in html
    image_identity = html[
        html.index("const imageIdentity = {"):
        html.index("const imageRecommendation = {")
    ]
    assert "productSection(" in image_identity


def test_chat_demo_query_uses_production_page_and_transport() -> None:
    client = TestClient(create_app())

    production = client.get("/chat")
    response = client.get("/chat?demo=1")

    assert response.status_code == 200
    assert response.text == production.text
    assert "guide-demo-fixture.js" not in response.text
    assert "GUIDE_DEMO_MODE" not in response.text
    assert "XiaoRoDemoFixture" not in response.text
    assert "fetch('/api/v1/chat/stream'" in response.text


def test_recording_query_cannot_replace_production_chat() -> None:
    client = TestClient(create_app())

    production = client.get("/chat")
    response = client.get("/chat?demo=recording-v1")

    assert response.status_code == 200
    assert response.text == production.text
    assert "/static/recording-v1/" not in response.text
    assert "fetch('/api/v1/chat/stream'" in response.text
    assert "no-store" in response.headers["cache-control"]


def test_runtime_static_surface_excludes_raw_html_and_keeps_assets() -> None:
    client = TestClient(create_app())

    for path in (
        "/static/chat.html",
        "/static/demo.html",
        "/static/knowledge.html",
    ):
        assert client.get(path).status_code == 404

    for path in (
        "/static/vendor/feather.min.js",
        "/static/guide-presentation.js",
        "/static/images/products/jd_v3_100160480140.png",
        "/static/recording-v1/guide-presentation.js",
        "/static/recording-v1/vendor/feather.min.js",
        "/static/recording-v1/images/jd_v3_100160480140.png",
    ):
        assert client.get(path).status_code == 200
    for path in (
        "/static/guide-demo-fixture.js",
        "/static/recording-v1/guide-demo-fixture.js",
    ):
        assert client.get(path).status_code == 404


def test_recording_manifest_hashes_every_loaded_asset() -> None:
    root = REPO_ROOT / "app" / "static" / "recording-v1"
    manifest = json.loads(
        (root / "manifest.json").read_text(encoding="utf-8")
    )

    assert manifest["version"] == "recording-v1"
    assert set(manifest["assets"]) == {
        "chat.html",
        "guide-presentation.js",
        "guide-demo-fixture.js",
        "vendor/feather.min.js",
        "images/jd_v3_100022610146.png",
        "images/jd_v3_100049220178.png",
        "images/jd_v3_100160480140.png",
        "images/tmall_v3_998532090974.png",
        "images/jd_v3_10069603621835.png",
        "images/jd_v3_100005935030.png",
        "images/jd_v3_100022610088.png",
    }
    assert all(
        digest == hashlib.sha256((root / name).read_bytes()).hexdigest()
        for name, digest in manifest["assets"].items()
    )
    fixture = (root / "guide-demo-fixture.js").read_text(
        encoding="utf-8"
    )
    assert "/static/images/products/" not in fixture


def test_health_exposes_single_unified_router() -> None:
    client = TestClient(create_app())

    health = client.get("/health")

    assert health.status_code == 200
    assert health.json()["turn_router"] == "unified_v1"


def test_health_cannot_be_switched_back_to_legacy_router(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GUIDE_UNIFIED_ROUTER_ENABLED", "false")
    client = TestClient(create_app())

    health = client.get("/health")

    assert health.status_code == 200
    assert health.json()["turn_router"] == "unified_v1"


def test_direct_processor_stream_is_not_a_production_entrypoint() -> None:
    import inspect

    from app.guide_runtime import composition
    from app.guide_runtime import sse

    runtime_source = (
        REPO_ROOT / "app" / "guide_runtime" / "app.py"
    ).read_text(encoding="utf-8")
    sse_source = (
        REPO_ROOT / "app" / "guide_runtime" / "sse.py"
    ).read_text(encoding="utf-8")
    local_browser_source = (
        REPO_ROOT / "tools" / "guide_gates" / "local_browser_app.py"
    ).read_text(encoding="utf-8")

    assert "build_runtime_orchestrator" not in runtime_source
    assert not hasattr(composition, "build_runtime_orchestrator")
    assert "orchestrator" not in inspect.signature(create_app).parameters
    assert not hasattr(sse, "_UnifiedImageFlowAdapter")
    assert "build_runtime_orchestrator" not in local_browser_source
    assert "orchestrator=" not in local_browser_source
    assert "consultation_runtime.consultation" not in sse_source
    assert "consultation_runtime.recommendation" not in sse_source


def test_default_runtime_composes_fixed_image_processor_before_requests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.guide.adapters.image import openclip_adapter

    model_loads = 0

    def unexpected_model_load(*args, **kwargs):
        del args, kwargs
        nonlocal model_loads
        model_loads += 1
        raise AssertionError("OpenCLIP must remain unloaded at composition")

    monkeypatch.setattr(
        openclip_adapter,
        "_load_locked_runtime",
        unexpected_model_load,
    )

    runtime_app = create_app()
    runtime = runtime_app.state.guide_runtime
    registry = runtime.unified._processor_registry

    assert registry["image_identity"] is runtime.image_processor
    assert registry["image_comparison"] is runtime.image_processor
    assert runtime.image_runtime.processor is runtime.image_processor
    assert not hasattr(runtime.image_runtime, "get_orchestrator")
    assert model_loads == 0


def test_http_text_always_enters_unified_guide_flow() -> None:
    from app.guide_runtime.sse import iter_http_events

    unified = RecordingUnifiedIngress()

    events = list(
        iter_http_events(
            unified,
            ChatStreamRequest(
                message="推荐防晒",
                session_id="runtime-unified-text-ingress",
            ),
            profile_owner=_runtime_owner(),
        )
    )

    assert events[-1].startswith(b"event: end\n")
    assert len(unified.text_calls) == 1
    turn = unified.text_calls[0]
    assert turn.identity.session_id == "runtime-unified-text-ingress"
    assert turn.identity.request_id.startswith("request_")
    assert turn.identity.turn_id.startswith("turn_")
    assert turn.identity.request_id != (
        "runtime-unified-text-ingress:request:1"
    )
    assert turn.identity.turn_id != (
        "runtime-unified-text-ingress:turn:1"
    )


def test_http_ingress_creates_unique_identity_for_each_request() -> None:
    from app.guide_runtime.sse import iter_http_events

    unified = RecordingUnifiedIngress()
    payload = ChatStreamRequest(
        message="推荐防晒",
        session_id="runtime-identity-unique",
    )
    list(
        iter_http_events(
            unified,
            payload,
            profile_owner=_runtime_owner(),
        )
    )
    list(
        iter_http_events(
            unified,
            payload,
            profile_owner=_runtime_owner(),
        )
    )

    first, second = unified.text_calls
    assert first.identity.request_id != second.identity.request_id
    assert first.identity.turn_id != second.identity.turn_id


def test_http_consultation_always_enters_unified_guide_flow() -> None:
    from app.guide_runtime.sse import iter_http_events

    unified = RecordingUnifiedIngress()

    events = list(
        iter_http_events(
            unified,
            ChatStreamRequest(
                message="我不知道自己是什么肤质",
                session_id="runtime-unified-consultation-ingress",
            ),
            profile_owner=_runtime_owner(),
        )
    )

    assert events[-1].startswith(b"event: end\n")
    assert len(unified.text_calls) == 1


def test_http_image_enters_the_same_unified_stream_as_text() -> None:
    from app.guide_runtime.sse import iter_http_events

    unified = RecordingUnifiedIngress()
    payload = ChatStreamRequest(
        message="这是什么商品",
        session_id="runtime-unified-image-ingress",
        conversation_version=0,
        image_bundle_id="bundle_" + "a" * 32,
        image_bundle_version=1,
        image_bundle_token="owner_" + "b" * 43,
    )

    events = list(
        iter_http_events(
            unified,
            payload,
            profile_owner=_runtime_owner(),
        )
    )

    assert events[-1].startswith(b"event: end\n")
    assert unified.image_calls == []
    assert len(unified.text_calls) == 1
    assert unified.text_calls[0].session_id == (
        "runtime-unified-image-ingress"
    )


def test_unified_router_flag_routes_real_text_and_commits_focus(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app.guide_runtime.composition import (
        build_consultation_vertical_runtime,
    )

    monkeypatch.setenv("GUIDE_UNIFIED_ROUTER_ENABLED", "true")
    vertical = build_consultation_vertical_runtime(
        state_dir=tmp_path / "unified-state",
    )
    client = TestClient(
        create_app(
            consultation_runtime=vertical,
        )
    )

    response = client.post(
        "/api/v1/chat/stream",
        json={
            "message": "500 元内敏感肌修护精华",
            "session_id": "runtime-unified-text",
            "conversation_version": 0,
        },
    )
    events = _events(response)

    assert response.status_code == 200
    assert events[-1] == (
        "end",
        {"conversation_version": 1},
    )
    products = next(
        data["products"]
        for name, data in events
        if name == "products"
    )
    assert [item["product_id"] for item in products] == [38, 91]
    stored = vertical.conversation_state.load("runtime-unified-text")
    assert stored is not None
    assert stored.active_owner is Responsibility.RECOMMENDATION
    assert stored.active_focus is not None
    assert stored.active_focus.slot == "recommendation"


def test_unified_router_recommendation_batch_can_be_compared(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app.guide_runtime.composition import (
        build_consultation_vertical_runtime,
    )

    monkeypatch.setenv("GUIDE_UNIFIED_ROUTER_ENABLED", "true")
    vertical = build_consultation_vertical_runtime(
        state_dir=tmp_path / "unified-text-comparison-state",
        semantic_intent=exact_echo_understanding(),
    )
    client = TestClient(
        create_app(
            consultation_runtime=vertical,
        )
    )
    session_id = "runtime-unified-text-comparison"

    first = _events(
        client.post(
            "/api/v1/chat/stream",
            json={
                "message": "500 元内敏感肌修护精华",
                "session_id": session_id,
                "conversation_version": 0,
            },
        )
    )
    second = _events(
        client.post(
            "/api/v1/chat/stream",
            json={
                "message": "这两款哪款更适合我现在敏感泛红",
                "session_id": session_id,
                "conversation_version": 1,
            },
        )
    )
    second_names = [name for name, _ in second]

    assert [name for name, _ in first][-1] == "end"
    assert "error" not in second_names
    assert second_names[-1] == "end"
    presentation = next(
        data
        for name, data in second
        if name == "presentation_contract"
    )
    assert presentation["mode"] == "comparison"
    assert [row["label"] for row in presentation["comparison_rows"]]
    assert presentation["winner"]["status"] in {
        "selected",
        "tied",
        "insufficient",
    }
    assert [
        data["mode"]
        for name, data in second
        if name == "card_display_contract"
    ] == ["comparison"]


def test_unified_router_text_recording_path_keeps_one_contract_per_turn(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app.guide.understanding.contracts import TopicCode
    from app.guide.understanding.turn_meaning_contracts import TurnMeaning
    from app.guide_runtime.composition import (
        build_consultation_vertical_runtime,
    )

    class RecordingPathSemanticPort:
        def propose(self, message, context):
            del context
            operation, topic, references = {
                "500 元内敏感肌修护精华": (
                    "recommendation",
                    TopicCode.SERUM,
                    (),
                ),
                "第二款的质地和使用顺序具体怎样": (
                    "knowledge",
                    None,
                    (
                        {
                            "raw_text": "第二款",
                            "object_family_hint": "product",
                            "ordinal_hint": 2,
                            "plurality_hint": "single",
                        },
                    ),
                ),
                "回到刚才的推荐，这两款哪款更适合我现在敏感泛红": (
                    "suitability",
                    None,
                    (
                        {
                            "raw_text": "这两款",
                            "object_family_hint": "product",
                            "ordinal_hint": None,
                            "plurality_hint": "batch",
                            "batch_size_hint": 2,
                        },
                    ),
                ),
                "第二款的规格和用法再讲清楚": (
                    "knowledge",
                    None,
                    (
                        {
                            "raw_text": "第二款",
                            "object_family_hint": "product",
                            "ordinal_hint": 2,
                            "plurality_hint": "single",
                        },
                    ),
                ),
                "烟酰胺和视黄醇是不是同一种成分": (
                    "knowledge",
                    TopicCode.SKINCARE,
                    (),
                ),
            }[message]
            return TurnMeaning(
                operation_hint=operation,
                recommendation_mode=(
                    "explore"
                    if operation == "recommendation"
                    else None
                ),
                recommendation_mode_basis=(
                    {
                        "basis": "bounded_exploration",
                        "source_text": "500 元内",
                    }
                    if operation == "recommendation"
                    else None
                ),
                recommendation_count=None,
                topic_hint=topic.value if topic is not None else None,
                continuity_hint=(
                    "new_task"
                    if message
                    in {
                        "500 元内敏感肌修护精华",
                        "烟酰胺和视黄醇是不是同一种成分",
                    }
                        else (
                            "return_to_focus"
                            if message.startswith("回到")
                            else "continue"
                        )
                ),
                subject_scope_hint="self",
                reference_mentions=references,
                product_mentions=(),
                budget_candidates=(),
                observation_candidates=(),
                preference_candidates=(),
                relative_candidates=(),
                consultation_hypothesis=None,
                next_observation_gap=None,
                question_meaning=message,
                safety_language="ordinary",
            )

    vertical = build_consultation_vertical_runtime(
        state_dir=tmp_path / "unified-text-recording-state",
        semantic_intent=RecordingPathSemanticPort(),
    )
    client = TestClient(
        create_app(
            consultation_runtime=vertical,
        )
    )
    session_id = "runtime-unified-text-recording"
    turns = (
        ("500 元内敏感肌修护精华", "recommendation"),
        (
            "回到刚才的推荐，这两款哪款更适合我现在敏感泛红",
            "comparison",
        ),
        ("第二款的质地和使用顺序具体怎样", "product_knowledge"),
        ("烟酰胺和视黄醇是不是同一种成分", "general_knowledge"),
    )

    for version, (message, expected_mode) in enumerate(turns):
        events = _events(
            client.post(
                "/api/v1/chat/stream",
                json={
                    "message": message,
                    "session_id": session_id,
                    "conversation_version": version,
                },
            )
        )

        assert "error" not in [name for name, _ in events], (
            message,
            events,
        )
        assert events[-1] == (
            "end",
            {"conversation_version": version + 1},
        )
        presentations = [
            data
            for name, data in events
            if name == "presentation_contract"
        ]
        assert len(presentations) == 1, (message, events)
        assert presentations[0]["mode"] == expected_mode


def test_unified_router_switches_from_consultation_to_recommendation(
    tmp_path: Path,
) -> None:
    from app.guide.understanding.turn_meaning_contracts import TurnMeaning
    from app.guide_runtime.composition import (
        build_consultation_vertical_runtime,
    )

    class ConsultationSwitchMeaningPort:
        def propose(self, message, context):
            del context
            if message == "先看防晒":
                return TurnMeaning(
                    operation_hint="recommendation",
                    recommendation_mode="explore",
                    recommendation_mode_basis={
                        "basis": "broad_exploration",
                        "source_text": message,
                    },
                    recommendation_count=None,
                    topic_hint="sunscreen",
                    continuity_hint="new_task",
                    subject_scope_hint="self",
                    reference_mentions=(),
                    product_mentions=(),
                    budget_candidates=(),
                    observation_candidates=(),
                    preference_candidates=(),
                    relative_candidates=(),
                    consultation_hypothesis=None,
                    next_observation_gap=None,
                    question_meaning=message,
                    safety_language="ordinary",
                )
            observations = (
                (
                    {
                        "observation_id": "obs_tightness",
                        "code": "tightness",
                        "present": True,
                        "qualifier": None,
                        "raw_text": message,
                    },
                )
                if message == "会"
                else ()
            )
            return TurnMeaning(
                operation_hint="assessment",
                topic_hint="skincare",
                continuity_hint=(
                    "new_task"
                    if message == "我不知道自己是什么肤质"
                    else "continue"
                ),
                subject_scope_hint="self",
                reference_mentions=(),
                product_mentions=(),
                budget_candidates=(),
                observation_candidates=observations,
                preference_candidates=(),
                relative_candidates=(),
                consultation_hypothesis=None,
                next_observation_gap=(
                    "active_damage_risk"
                    if message == "我不知道自己是什么肤质"
                    else "persistence_or_trigger"
                ),
                question_meaning=message,
                safety_language="ordinary",
            )

    vertical = build_consultation_vertical_runtime(
        state_dir=tmp_path / "unified-switch-state",
        semantic_intent=ConsultationSwitchMeaningPort(),
    )
    client = TestClient(
        create_app(
            consultation_runtime=vertical,
        )
    )
    session_id = "runtime-unified-switch"

    entered = _events(
        client.post(
            "/api/v1/chat/stream",
            json={
                "message": "我不知道自己是什么肤质",
                "session_id": session_id,
                "conversation_version": 0,
            },
        )
    )
    answered = _events(
        client.post(
            "/api/v1/chat/stream",
            json={
                "message": "会",
                "session_id": session_id,
                "conversation_version": 1,
            },
        )
    )
    switched = _events(
        client.post(
            "/api/v1/chat/stream",
            json={
                "message": "先看防晒",
                "session_id": session_id,
                "conversation_version": 2,
            },
        )
    )

    assert entered[-1] == ("end", {"conversation_version": 1})
    assert any(
        name == "consultation_observation"
        for name, _ in answered
    )
    assert answered[-1] == ("end", {"conversation_version": 2})
    assert any(name == "products" for name, _ in switched)
    assert switched[-1] == ("end", {"conversation_version": 3})
    stored = vertical.conversation_state.load(session_id)
    assert stored is not None
    assert stored.consultation_slot is not None
    assert stored.active_owner is Responsibility.RECOMMENDATION
    assert stored.active_focus is not None
    assert stored.active_focus.slot == "recommendation"


def test_unified_router_owns_image_turn_through_its_only_stream(
) -> None:
    from app.guide.feedback.profile_contracts import ProfileOwnerRef
    from app.guide.presentation.sse_events import (
        ClarifyData,
        ClarifyEvent,
        EndData,
        EndEvent,
    )
    from app.guide.understanding.semantic_contracts import (
        ClarificationCode,
    )
    from app.guide_runtime.sse import iter_http_events

    class RecordingUnified:
        def __init__(self) -> None:
            self.calls = []

        def stream(self, turn):
            self.calls.append(turn)
            yield from _clarification_events(turn)

    owner = ProfileOwnerRef(
        scope="anonymous_browser",
        subject_id="runtime_unified_image_owner_0123456789",
    )
    unified = RecordingUnified()
    payload = ChatStreamRequest(
        message="这是什么商品",
        session_id="runtime-unified-image",
        conversation_version=0,
        image_bundle_id="bundle_" + "a" * 32,
        image_bundle_version=1,
        image_bundle_token="owner_" + "b" * 43,
    )

    events = list(
        iter_http_events(
            unified,
            payload,
            profile_owner=owner,
        )
    )

    assert [
        frame.split(b"\n", maxsplit=1)[0]
        for frame in events
    ] == [
        b"event: start",
        b"event: intent",
        b"event: clarify",
        b"event: end",
    ]
    assert len(unified.calls) == 1
    assert unified.calls[0].session_id == "runtime-unified-image"


def test_unified_router_real_image_persists_confirmed_focus(
    tmp_path: Path,
) -> None:
    from app.guide.understanding.turn_meaning_contracts import TurnMeaning
    from app.guide_runtime.composition import (
        build_consultation_vertical_runtime,
    )
    from tests.guide.runtime.test_composition import StoredVectorEncoder

    class ImageSimilarityMeaningPort:
        def propose(self, message, context):
            del context
            return TurnMeaning(
                operation_hint="image_similarity",
                recommendation_mode="explore",
                recommendation_mode_basis={
                    "basis": "similar_alternatives",
                    "source_text": "相似款",
                },
                recommendation_count=None,
                topic_hint="sunscreen",
                continuity_hint="new_task",
                subject_scope_hint="self",
                reference_mentions=(
                    {
                        "raw_text": "相似款",
                        "object_family_hint": "image",
                        "ordinal_hint": 1,
                        "plurality_hint": "single",
                    },
                ),
                product_mentions=(),
                budget_candidates=(
                    {
                        "raw_text": "150元以内",
                        "relation": "maximum",
                        "minimum": None,
                        "maximum": "150",
                    },
                ),
                observation_candidates=(),
                preference_candidates=(),
                relative_candidates=(),
                consultation_hypothesis=None,
                next_observation_gap=None,
                question_meaning=message,
                safety_language="ordinary",
            )

    state_root = tmp_path / "unified-image-state"
    service = build_image_bundle_service(
        database_path=state_root / "image-bundles.sqlite3"
    )
    vertical = _build_with_image_encoder(
        StoredVectorEncoder(53),
        state_dir=state_root,
        semantic_intent=ImageSimilarityMeaningPort(),
        image_bundle_service=service,
    )
    client = TestClient(
        create_app(
            consultation_runtime=vertical,
            image_bundle_service=service,
        )
    )
    session_id = "runtime-unified-real-image"
    receipt = _upload_bundle(client, session_id=session_id)

    events = _events(
        client.post(
            "/api/v1/chat/stream",
            json={
                "message": "150元以内找防晒相似款",
                "session_id": session_id,
                "conversation_version": 0,
                "image_bundle_id": receipt["bundle_id"],
                "image_bundle_version": receipt["version"],
                "image_bundle_token": receipt["owner_token"],
            },
        )
    )

    assert any(
        name == "presentation_contract"
        for name, _ in events
    ), events
    presentation = next(
        data
        for name, data in events
        if name == "presentation_contract"
    )
    products = next(
        data["products"]
        for name, data in events
        if name == "products"
    )
    observation = next(
        data["observation"]
        for name, data in events
        if name == "image_observation"
    )
    assert presentation["mode"] == "recommendation"
    assert presentation["responsibility"] == "recommendation"
    assert next(
        data["intent"]
        for name, data in events
        if name == "intent"
    ) == "image_recommend"
    assert 53 not in {item["id"] for item in products}
    assert {
        item["id"] for item in products
    }.issubset(set(observation["candidate_product_ids"]))
    assert events[-1] == ("end", {"conversation_version": 1})
    stored = vertical.conversation_state.load(session_id)
    assert stored is not None
    assert stored.active_owner is Responsibility.RECOMMENDATION
    assert stored.active_focus is not None
    assert stored.active_focus.slot == "recommendation"
    assert [
        item.product_id
        for item in stored.image_slot.confirmed_products
    ] == [53]


def test_runtime_explicit_product_with_current_upload_persists_dormant_image_lane(
    tmp_path: Path,
) -> None:
    from app.guide.understanding.turn_meaning_contracts import TurnMeaning
    from app.guide_runtime.composition import (
        build_consultation_vertical_runtime,
    )
    from tests.guide.runtime.test_composition import StoredVectorEncoder

    class ExplicitProductMeaningPort:
        def translate(self, message, *, context):
            del context
            return TurnMeaning(
                operation_hint="knowledge",
                topic_hint="serum",
                continuity_hint="new_task",
                subject_scope_hint="self",
                reference_mentions=(),
                product_mentions=({"raw_text": "B5精华"},),
                budget_candidates=(),
                observation_candidates=(),
                preference_candidates=(),
                relative_candidates=(),
                consultation_hypothesis=None,
                next_observation_gap=None,
                question_meaning=message,
                safety_language="ordinary",
            )

    state_root = tmp_path / "explicit-product-image-state"
    service = build_image_bundle_service(
        database_path=state_root / "image-bundles.sqlite3"
    )
    vertical = _build_with_image_encoder(
        StoredVectorEncoder(53),
        state_dir=state_root,
        semantic_intent=ExplicitProductMeaningPort(),
        image_bundle_service=service,
    )
    client = TestClient(
        create_app(
            consultation_runtime=vertical,
            image_bundle_service=service,
        )
    )
    session_id = "runtime-explicit-product-current-upload"
    receipt = _upload_bundle(client, session_id=session_id)

    events = _events(
        client.post(
            "/api/v1/chat/stream",
            json={
                "message": "B5精华有什么资料",
                "session_id": session_id,
                "conversation_version": 0,
                "image_bundle_id": receipt["bundle_id"],
                "image_bundle_version": receipt["version"],
                "image_bundle_token": receipt["owner_token"],
            },
        )
    )

    assert events[-1] == ("end", {"conversation_version": 1})
    stored = vertical.conversation_state.load(session_id)
    assert stored is not None
    assert stored.active_focus is not None
    assert stored.active_focus.slot != "image"
    assert tuple(
        item.product_id
        for item in stored.image_slot.confirmed_products
    ) == (53,)


def test_unified_router_image_suitability_preserves_single_product_contract(
    tmp_path: Path,
) -> None:
    from app.guide.understanding.turn_meaning_contracts import TurnMeaning
    from app.guide_runtime.composition import (
        build_consultation_vertical_runtime,
    )
    from tests.guide.runtime.test_composition import StoredVectorEncoder

    class ImageSuitabilityMeaningPort:
        def propose(self, message, context):
            del context
            return TurnMeaning(
                operation_hint="suitability",
                topic_hint="sunscreen",
                continuity_hint="new_task",
                subject_scope_hint="self",
                reference_mentions=(
                    {
                        "raw_text": "这张图",
                        "object_family_hint": "image",
                        "ordinal_hint": 1,
                        "plurality_hint": "single",
                    },
                ),
                preference_candidates=(
                    {
                        "field_key": "skin",
                        "concept_id": "skin.sensitive",
                        "raw_text": "敏感肌",
                        "polarity": "prefer",
                        "strength": "ordinary",
                    },
                ),
                question_meaning="判断图片商品是否适合敏感肌",
                safety_language="ordinary",
            )

    state_root = tmp_path / "unified-image-suitability-state"
    service = build_image_bundle_service(
        database_path=state_root / "image-bundles.sqlite3"
    )
    vertical = _build_with_image_encoder(
        StoredVectorEncoder(53),
        state_dir=state_root,
        semantic_intent=ImageSuitabilityMeaningPort(),
        image_bundle_service=service,
    )
    client = TestClient(
        create_app(
            consultation_runtime=vertical,
            image_bundle_service=service,
        )
    )
    session_id = "runtime-unified-image-suitability"
    receipt = _upload_bundle(client, session_id=session_id)

    events = _events(
        client.post(
            "/api/v1/chat/stream",
            json={
                "message": "这张图适合敏感肌吗",
                "session_id": session_id,
                "conversation_version": 0,
                "image_bundle_id": receipt["bundle_id"],
                "image_bundle_version": receipt["version"],
                "image_bundle_token": receipt["owner_token"],
            },
        )
    )

    presentation = next(
        data
        for name, data in events
        if name == "presentation_contract"
    )
    products = next(
        data["products"]
        for name, data in events
        if name == "products"
    )

    assert presentation["responsibility"] == "single_product_suitability"
    assert presentation["mode"] == "single_product"
    assert [item["id"] for item in products] == [53]
    assert events[-1] == ("end", {"conversation_version": 1})
    stored = vertical.conversation_state.load(session_id)
    assert stored is not None
    assert (
        stored.active_owner
        is Responsibility.SINGLE_PRODUCT_SUITABILITY
    )
    assert stored.active_focus is not None
    assert stored.active_focus.slot == "product"
    assert stored.active_focus.object_id == 53
    assert [
        item.product_id
        for item in stored.image_slot.confirmed_products
    ] == [53]


def test_unified_router_typed_image_identity_persists_question_summary(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app.guide_runtime.composition import (
        build_consultation_vertical_runtime,
    )
    from tests.guide.runtime.test_composition import StoredVectorEncoder

    monkeypatch.setenv("GUIDE_UNIFIED_ROUTER_ENABLED", "true")
    state_root = tmp_path / "unified-typed-image-state"
    service = build_image_bundle_service(
        database_path=state_root / "image-bundles.sqlite3"
    )
    vertical = _build_with_image_encoder(
        StoredVectorEncoder(53),
        state_dir=state_root,
        semantic_intent=exact_echo_understanding(),
        image_bundle_service=service,
    )
    client = TestClient(
        create_app(
            consultation_runtime=vertical,
            image_bundle_service=service,
        )
    )
    session_id = "runtime-unified-typed-image"
    receipt = _upload_bundle(client, session_id=session_id)

    events = _events(
        client.post(
            "/api/v1/chat/stream",
            json={
                "message": "",
                "image_action": "identify",
                "session_id": session_id,
                "conversation_version": 0,
                "image_bundle_id": receipt["bundle_id"],
                "image_bundle_version": receipt["version"],
                "image_bundle_token": receipt["owner_token"],
            },
        )
    )

    assert any(
        name == "presentation_contract"
        for name, _ in events
    ), events
    assert events[-1] == ("end", {"conversation_version": 1})
    stored = vertical.conversation_state.load(session_id)
    assert stored is not None
    assert stored.active_owner is Responsibility.IMAGE_IDENTITY
    assert stored.active_focus is not None
    assert stored.active_focus.slot == "image"
    assert stored.active_focus.object_id == 53


def test_unified_router_two_images_use_standard_comparison(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app.guide.understanding.turn_meaning_contracts import TurnMeaning
    from app.guide_runtime.composition import (
        build_consultation_vertical_runtime,
    )
    from tests.guide.runtime.test_composition import StoredVectorEncoder

    class ComparisonTranslator:
        def translate(self, message, *, context):
            meaning = TurnMeaning(
                operation_hint="comparison",
                topic_hint=None,
                continuity_hint="new_task",
                subject_scope_hint="self",
                reference_mentions=(
                    {
                        "raw_text": "这两张图",
                        "object_family_hint": "image",
                        "ordinal_hint": None,
                        "plurality_hint": "batch",
                    },
                ),
                question_meaning=message,
                safety_language="ordinary",
            )
            return meaning

    monkeypatch.setenv("GUIDE_UNIFIED_ROUTER_ENABLED", "true")
    state_root = tmp_path / "unified-image-comparison-state"
    service = build_image_bundle_service(
        database_path=state_root / "image-bundles.sqlite3"
    )
    vertical = _build_with_image_encoder(
        StoredVectorEncoder((53, 55)),
        state_dir=state_root,
        semantic_intent=ComparisonTranslator(),
        image_bundle_service=service,
    )
    client = TestClient(
        create_app(
            consultation_runtime=vertical,
            image_bundle_service=service,
        )
    )
    session_id = "runtime-unified-two-images"
    receipt = _upload_bundle(
        client,
        session_id=session_id,
        count=2,
    )

    events = _events(
        client.post(
            "/api/v1/chat/stream",
            json={
                "message": "比较这两张图",
                "session_id": session_id,
                "conversation_version": 0,
                "image_bundle_id": receipt["bundle_id"],
                "image_bundle_version": receipt["version"],
                "image_bundle_token": receipt["owner_token"],
            },
        )
    )

    presentation = next(
        data
        for name, data in events
        if name == "presentation_contract"
    )
    products = next(
        data["products"]
        for name, data in events
        if name == "products"
    )
    assert presentation["mode"] == "comparison"
    assert [item["id"] for item in products] == [53, 55]
    assert events[-1] == ("end", {"conversation_version": 1})
    stored = vertical.conversation_state.load(session_id)
    assert stored is not None
    assert stored.active_owner is Responsibility.COMPARISON
    assert stored.active_focus is not None
    assert stored.active_focus.slot == "image"
    assert [
        item.product_id
        for item in stored.image_slot.confirmed_products
    ] == [53, 55]


def test_runtime_single_image_sse_returns_real_cards_and_versions(
    tmp_path: Path,
) -> None:
    from app.guide.understanding.turn_meaning_contracts import TurnMeaning
    from app.guide_runtime.composition import (
        build_consultation_vertical_runtime,
    )
    from tests.guide.runtime.test_composition import StoredVectorEncoder

    class ImageSimilarityMeaningPort:
        def propose(self, message, context):
            del context
            return TurnMeaning(
                operation_hint="image_similarity",
                recommendation_mode="explore",
                recommendation_mode_basis={
                    "basis": "similar_alternatives",
                    "source_text": "相似款",
                },
                recommendation_count=None,
                topic_hint="sunscreen",
                continuity_hint="new_task",
                subject_scope_hint="self",
                reference_mentions=(
                    {
                        "raw_text": "相似款",
                        "object_family_hint": "image",
                        "ordinal_hint": 1,
                        "plurality_hint": "single",
                    },
                ),
                product_mentions=(),
                budget_candidates=(
                    {
                        "raw_text": "150元以内",
                        "relation": "maximum",
                        "minimum": None,
                        "maximum": "150",
                    },
                ),
                observation_candidates=(),
                preference_candidates=(),
                relative_candidates=(),
                consultation_hypothesis=None,
                next_observation_gap=None,
                question_meaning=message,
                safety_language="ordinary",
            )

    state_root = tmp_path / "guide-state"
    service = build_image_bundle_service(
        database_path=state_root / "image-bundles.sqlite3"
    )
    vertical = _build_with_image_encoder(
        StoredVectorEncoder(53),
        state_dir=state_root,
        semantic_intent=ImageSimilarityMeaningPort(),
        image_bundle_service=service,
    )
    client = TestClient(
        create_app(
            consultation_runtime=vertical,
            image_bundle_service=service,
        )
    )
    source = (
        REPO_ROOT
        / "app"
        / "static"
        / "images"
        / "products"
        / "taobao_v3_572910260362.png"
    )
    upload = client.post(
        "/api/v1/chat/image-bundles",
        data={"session_id": "runtime-real-image"},
        files=[
            (
                "images",
                (source.name, source.read_bytes(), "image/png"),
            )
        ],
    )
    assert upload.status_code == 201
    receipt = upload.json()

    response = client.post(
        "/api/v1/chat/stream",
        json={
            "message": "150元以内找相似款",
            "session_id": "runtime-real-image",
            "conversation_version": 0,
            "image_bundle_id": receipt["bundle_id"],
            "image_bundle_version": receipt["version"],
            "image_bundle_token": receipt["owner_token"],
        },
    )
    events = _events(response)

    observation = next(
        data for name, data in events if name == "image_observation"
    )["observation"]
    products = next(
        data for name, data in events if name == "products"
    )["products"]
    assert observation["confirmed_product_id"] == 53
    assert observation["model_name"] == guide_image_runtime_lock().model_name
    assert observation["index_sha256"] == (
        guide_image_runtime_lock().index_sha256
    )
    product_ids = [product["id"] for product in products]
    assert product_ids
    assert len(product_ids) == len(set(product_ids))
    assert 53 not in product_ids
    stored = vertical.conversation_state.load("runtime-real-image")
    assert stored is not None
    assert stored.recommendation_slot is not None
    assert [
        candidate.product_id
        for candidate in stored.recommendation_slot.candidates
    ] == product_ids
    assert (
        stored.recommendation_slot.query_context
        .similarity_anchor_product_id
        == 53
    )
    assert stored.image_slot is not None
    assert stored.image_slot.confirmed_products[0].product_id == 53
    assert all(product["image_url"] for product in products)
    assert all(product["detail_url"] for product in products)
    assert "图片已安全接收，识别尚未启用。" not in response.text


def test_runtime_invalid_wire_envelope_is_rejected_before_sqlite_commit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app.guide.application import execution_contracts
    from app.guide.application.public_event_envelope import (
        GuidePublicEventError,
    )
    from app.guide_runtime.composition import (
        build_consultation_vertical_runtime,
        build_feedback_service,
    )
    from tests.guide.runtime.test_composition import StoredVectorEncoder

    state_root = tmp_path / "guide-state"
    image_bundles = build_image_bundle_service(
        database_path=state_root / "image_bundles.sqlite3"
    )
    consultation_runtime = _build_with_image_encoder(
        StoredVectorEncoder(53),
        state_dir=state_root,
        semantic_intent=exact_echo_understanding(),
        image_bundle_service=image_bundles,
    )
    client = TestClient(
        create_app(
            consultation_runtime=consultation_runtime,
            image_bundle_service=image_bundles,
            feedback_service=build_feedback_service(
                state_directory=state_root
            ),
        )
    )
    session_id = "runtime-image-invalid-profile"
    receipt = _upload_bundle(client, session_id=session_id)
    original_materializer = (
        execution_contracts.materialize_public_event_envelope
    )

    def reject_invalid_envelope(*args, **kwargs):
        del args, kwargs
        raise GuidePublicEventError(
            code="GUIDE_EVENT_CONTRACT_INVALID",
            message="推荐响应不完整，请稍后重试。",
        )

    monkeypatch.setattr(
        execution_contracts,
        "materialize_public_event_envelope",
        reject_invalid_envelope,
    )

    response = client.post(
        "/api/v1/chat/stream",
        json={
            "message": "",
            "image_action": "identify",
            "session_id": session_id,
            "conversation_version": 0,
            "image_bundle_id": receipt["bundle_id"],
            "image_bundle_version": receipt["version"],
            "image_bundle_token": receipt["owner_token"],
        },
    )
    events = _events(response)
    snapshot = consultation_runtime.conversation_state.load(session_id)

    def feedback_target_count() -> int:
        with sqlite3.connect(
            state_root / "feedback_targets.sqlite3"
        ) as connection:
            return int(
                connection.execute(
                    "SELECT COUNT(*) FROM feedback_targets"
                ).fetchone()[0]
            )

    assert {
        "events": events,
        "durable_version": snapshot.version if snapshot is not None else 0,
        "feedback_target_count": feedback_target_count(),
    } == {
        "events": [
            ("start", {"session_id": session_id}),
            (
                "error",
                {
                    "error": "GUIDE_INTERNAL_ERROR",
                    "message": "推荐暂时不可用，请稍后重试。",
                },
            ),
        ],
        "durable_version": 0,
        "feedback_target_count": 0,
    }

    monkeypatch.setattr(
        execution_contracts,
        "materialize_public_event_envelope",
        original_materializer,
    )
    accepted_receipt = _upload_bundle(
        client,
        session_id=session_id,
    )
    accepted = _events(
        client.post(
            "/api/v1/chat/stream",
            json={
                "message": "",
                "image_action": "identify",
                "session_id": session_id,
                "conversation_version": 0,
                "image_bundle_id": accepted_receipt["bundle_id"],
                "image_bundle_version": accepted_receipt["version"],
                "image_bundle_token": accepted_receipt["owner_token"],
            },
        )
    )
    stored = consultation_runtime.conversation_state.load(session_id)

    assert accepted[-1] == ("end", {"conversation_version": 1})
    assert "feedback_target" not in {
        name for name, _ in accepted
    }
    assert stored is not None
    assert stored.version == 1
    assert feedback_target_count() == 0


def test_runtime_disconnect_after_business_commit_keeps_state() -> None:
    from app.guide.adapters.state import InMemoryConversationState
    from app.guide_runtime.composition import (
        build_consultation_vertical_runtime,
    )

    class CountingConversationState(InMemoryConversationState):
        def __init__(self) -> None:
            super().__init__()
            self.save_calls = 0

        def save(self, snapshot, *, expected_version):
            self.save_calls += 1
            return super().save(
                snapshot,
                expected_version=expected_version,
            )

    class RecordingFeedback:
        def __init__(self) -> None:
            self.completions = []

        def register_completed(self, *, actor, completion):
            del actor
            self.completions.append(completion)
            return None

    class DisconnectBeforeEnd:
        url = SimpleNamespace(scheme="http")

        def __init__(self) -> None:
            self.cookies = {}
            self.checks = 0

        async def is_disconnected(self) -> bool:
            self.checks += 1
            return self.checks == 14

    state = CountingConversationState()
    feedback = RecordingFeedback()
    vertical = build_consultation_vertical_runtime(
        conversation_state=state,
        semantic_intent=exact_echo_understanding(),
    )
    app = create_app(
        consultation_runtime=vertical,
        feedback_service=feedback,
    )
    route = next(
        route
        for route in app.routes
        if getattr(route, "path", None) == "/api/v1/chat/stream"
    )
    payload = ChatStreamRequest(
        message="500 元内敏感肌修护精华",
        session_id="runtime-public-event-delivery",
        conversation_version=0,
    )

    response = asyncio.run(
        route.endpoint(DisconnectBeforeEnd(), payload)
    )

    async def consume() -> list[bytes]:
        return [chunk async for chunk in response.body_iterator]

    chunks = asyncio.run(consume())

    assert b"event: end" not in b"".join(chunks)
    assert state.save_calls == 1
    stored = state.load("runtime-public-event-delivery")
    assert stored is not None
    assert stored.version == 1
    assert feedback.completions == []


def test_runtime_version_endpoint_reports_authoritative_committed_version(
) -> None:
    from app.guide.adapters.state import InMemoryConversationState
    from app.guide_runtime.composition import (
        build_consultation_vertical_runtime,
    )

    state = InMemoryConversationState()
    vertical = build_consultation_vertical_runtime(
        conversation_state=state,
        semantic_intent=exact_echo_understanding(),
    )
    client = TestClient(
        create_app(consultation_runtime=vertical)
    )
    session_id = "runtime-version-recovery"
    client.get("/chat")

    initial = client.get(
        f"/api/v1/chat/sessions/{session_id}/version"
    )
    streamed = client.post(
        "/api/v1/chat/stream",
        json={
            "message": "500 元内敏感肌修护精华",
            "session_id": session_id,
            "conversation_version": 0,
        },
    )
    committed = client.get(
        f"/api/v1/chat/sessions/{session_id}/version"
    )

    assert initial.status_code == 200
    assert initial.json() == {
        "session_id": session_id,
        "conversation_version": 0,
    }
    assert streamed.status_code == 200
    assert _events(streamed)[-1] == (
        "end",
        {"conversation_version": 1},
    )
    assert committed.status_code == 200
    assert committed.json() == {
        "session_id": session_id,
        "conversation_version": 1,
    }


def test_http_session_waiters_do_not_exhaust_shared_threadpool() -> None:
    import anyio
    import threading
    from fastapi import Response
    from starlette.concurrency import run_in_threadpool

    from app.guide.feedback.delivery import (
        FeedbackTargetRegistrationRequest,
    )
    from app.guide_runtime import sse

    class IdleConversationState:
        def load(self, session_id):
            del session_id
            return None

        def delete(self, session_id, *, expected_owner):
            del session_id, expected_owner
            return False

    class ByteOrchestrator:
        _conversation_state = IdleConversationState()

        def stream(self, turn):
            del turn
            yield b"event: end\ndata: {\"conversation_version\":0}\n\n"

    class ConnectedRequest:
        url = SimpleNamespace(scheme="http")
        cookies = {}

        async def is_disconnected(self) -> bool:
            return False

    class WaitingLock:
        def __init__(self) -> None:
            self.attempted = threading.Event()
            self.release = threading.Event()

        def __enter__(self):
            self.attempted.set()
            self.release.wait(timeout=2)
            return self

        def try_enter(self) -> bool:
            self.attempted.set()
            return self.release.is_set()

        def __exit__(self, *_: object) -> None:
            return None

    class WaitingRegistry:
        def __init__(self) -> None:
            self.lock = WaitingLock()

        def for_session(self, session_id):
            del session_id
            return self.lock

        def hold(self, session_id):
            del session_id
            return sse.hold_session_operation_lock(self.lock)

    runtime_app = create_app()
    runtime_app.state.orchestrator = ByteOrchestrator()
    routes = {
        route.path: route.endpoint
        for route in runtime_app.routes
        if hasattr(route, "endpoint")
    }

    async def invoke(operation: str, session_id: str):
        request = ConnectedRequest()
        if operation == "stream":
            response = await routes["/api/v1/chat/stream"](
                request,
                ChatStreamRequest(
                    message="推荐防晒",
                    session_id=session_id,
                    conversation_version=0,
                ),
            )
            try:
                return await anext(response.body_iterator)
            finally:
                await response.body_iterator.aclose()
        if operation == "version":
            return await routes[
                "/api/v1/chat/sessions/{session_id}/version"
            ](
                request,
                Response(),
                session_id,
            )
        if operation == "delete":
            return await routes[
                "/api/v1/chat/sessions/{session_id}"
            ](
                request,
                session_id,
            )
        return await routes[
            "/api/v1/chat/sessions/{session_id}/feedback-target"
        ](
            request,
            session_id,
            FeedbackTargetRegistrationRequest(
                conversation_version=1,
            ),
        )

    async def exercise() -> dict[str, bool]:
        limiter = anyio.to_thread.current_default_thread_limiter()
        previous_tokens = limiter.total_tokens
        shared_worker_available: dict[str, bool] = {}
        limiter.total_tokens = 1
        try:
            for operation in (
                "stream",
                "version",
                "delete",
                "feedback-target",
            ):
                registry = WaitingRegistry()
                runtime_app.state.session_operation_locks = registry
                pending = asyncio.create_task(
                    invoke(
                        operation,
                        f"http-session-waiter-{operation}",
                    )
                )
                for _ in range(200):
                    if registry.lock.attempted.is_set():
                        break
                    await asyncio.sleep(0.001)
                assert registry.lock.attempted.is_set()

                marker = threading.Event()
                marker_task = asyncio.create_task(
                    run_in_threadpool(marker.set)
                )
                await asyncio.sleep(0.05)
                shared_worker_available[operation] = marker.is_set()
                registry.lock.release.set()
                await marker_task
                await asyncio.gather(pending, return_exceptions=True)
        finally:
            limiter.total_tokens = previous_tokens
        return shared_worker_available

    availability = asyncio.run(exercise())

    assert availability == {
        "stream": True,
        "version": True,
        "delete": True,
        "feedback-target": True,
    }


@pytest.mark.parametrize(
    ("spec_version", "outcome"),
    [
        ("2.4", "send_error"),
        ("2.0", "disconnect"),
        ("2.4", "success"),
        ("2.0", "success"),
    ],
)
def test_runtime_asgi_terminal_delivery_boundary(
    spec_version,
    outcome,
) -> None:
    from app.guide.adapters.state import InMemoryConversationState
    from app.guide_runtime.composition import (
        build_consultation_vertical_runtime,
    )

    class CountingConversationState(InMemoryConversationState):
        def __init__(self) -> None:
            super().__init__()
            self.save_calls = 0

        def save(self, snapshot, *, expected_version):
            self.save_calls += 1
            return super().save(
                snapshot,
                expected_version=expected_version,
            )

    class ConnectedRequest:
        url = SimpleNamespace(scheme="http")
        cookies = {}

        async def is_disconnected(self) -> bool:
            return False

    state = CountingConversationState()
    feedback = _PreparedRecordingFeedback()
    vertical = build_consultation_vertical_runtime(
        conversation_state=state,
        semantic_intent=exact_echo_understanding(),
    )
    app = create_app(
        consultation_runtime=vertical,
        feedback_service=feedback,
    )
    route = next(
        route
        for route in app.routes
        if getattr(route, "path", None) == "/api/v1/chat/stream"
    )
    session_id = f"runtime-asgi-{spec_version}-{outcome}"
    payload = ChatStreamRequest(
        message="500 元内敏感肌修护精华",
        session_id=session_id,
        conversation_version=0,
    )

    async def exercise() -> list[dict[str, Any]]:
        response = await route.endpoint(ConnectedRequest(), payload)

        def assert_before_terminal_delivery() -> None:
            snapshot = state.load(session_id)
            assert state.save_calls == 1
            assert snapshot is not None
            assert snapshot.version == 1
            assert feedback.persisted == []

        def assert_committed() -> None:
            snapshot = state.load(session_id)
            assert state.save_calls == 1
            assert snapshot is not None
            assert snapshot.version == 1
            assert feedback.persisted == []

        return await _drive_asgi_terminal_delivery(
            response,
            spec_version=spec_version,
            outcome=outcome,
            assert_before_terminal_delivery=(
                assert_before_terminal_delivery
            ),
            assert_committed=assert_committed,
        )

    sent = asyncio.run(exercise())
    terminal_bodies = [
        bytes(message.get("body", b""))
        for message in sent
        if message["type"] == "http.response.body"
        and b"event: end\n" in bytes(message.get("body", b""))
    ]
    assert len(terminal_bodies) == 1


def test_runtime_terminal_end_is_not_post_mutated() -> None:
    from app.guide.adapters.state import InMemoryConversationState
    from app.guide_runtime.composition import (
        build_consultation_vertical_runtime,
    )

    class CountingConversationState(InMemoryConversationState):
        def __init__(self) -> None:
            super().__init__()
            self.save_calls = 0

        def save(self, snapshot, *, expected_version):
            self.save_calls += 1
            return super().save(
                snapshot,
                expected_version=expected_version,
            )

    class RecordingFeedback:
        def __init__(self) -> None:
            self.completions = []

        def prepare_completed(self, *, actor, completion):
            del actor
            self.completions.append(completion)
            return SimpleNamespace(
                receipt=FeedbackTargetReceipt(
                    conversation_version=completion.conversation_version,
                    displayed_product_ids=tuple(
                        completion.card_display.visible_product_ids
                    ),
                    profile_version=None,
                )
            )

        def persist_prepared(self, prepared):
            return prepared.receipt

        def register_completed(self, *, actor, completion):
            prepared = self.prepare_completed(
                actor=actor,
                completion=completion,
            )
            return self.persist_prepared(prepared)

    class ConnectedRequest:
        url = SimpleNamespace(scheme="http")
        cookies = {}

        async def is_disconnected(self) -> bool:
            return False

    state = CountingConversationState()
    feedback = RecordingFeedback()
    vertical = build_consultation_vertical_runtime(
        conversation_state=state,
        semantic_intent=exact_echo_understanding(),
    )
    app = create_app(
        consultation_runtime=vertical,
        feedback_service=feedback,
    )
    route = next(
        route
        for route in app.routes
        if getattr(route, "path", None) == "/api/v1/chat/stream"
    )
    session_id = "runtime-atomic-terminal"
    payload = ChatStreamRequest(
        message="500 元内敏感肌修护精华",
        session_id=session_id,
        conversation_version=0,
    )

    async def consume_until_feedback_target():
        response = await route.endpoint(ConnectedRequest(), payload)
        stream = response.body_iterator
        terminal_chunk = None
        try:
            async for chunk in stream:
                names = [
                    name
                    for name, _ in _events(
                        SimpleNamespace(text=chunk)
                    )
                ]
                if "feedback_target" in names or "end" in names:
                    terminal_chunk = chunk
        finally:
            await stream.aclose()
        return terminal_chunk

    terminal_chunk = asyncio.run(consume_until_feedback_target())
    terminal_events = (
        _events(SimpleNamespace(text=terminal_chunk))
        if terminal_chunk is not None
        else []
    )
    snapshot = state.load(session_id)

    terminal_names = [name for name, _ in terminal_events]
    assert {
        "terminal_names": terminal_names,
        "saw_feedback_target": "feedback_target" in terminal_names,
        "saw_end": "end" in terminal_names,
        "state": snapshot.version if snapshot is not None else 0,
        "state_commits": state.save_calls,
        "feedback": len(feedback.completions),
    } == {
        "terminal_names": ["end"],
        "saw_feedback_target": False,
        "saw_end": True,
        "state": 1,
        "state_commits": 1,
        "feedback": 0,
    }


def test_runtime_registers_feedback_target_from_committed_snapshot(
    tmp_path: Path,
) -> None:
    from app.guide_runtime.composition import (
        build_consultation_vertical_runtime,
        build_feedback_service,
    )

    state_root = tmp_path / "state"
    vertical = build_consultation_vertical_runtime(
        state_dir=state_root,
        semantic_intent=exact_echo_understanding(),
    )
    feedback = build_feedback_service(state_directory=state_root)
    client = TestClient(
        create_app(
            consultation_runtime=vertical,
            feedback_service=feedback,
        )
    )
    session_id = "runtime-feedback-target"
    events = _events(
        client.post(
            "/api/v1/chat/stream",
            json={
                "message": "500 元内敏感肌修护精华",
                "session_id": session_id,
                "conversation_version": 0,
            },
        )
    )
    products = next(
        data["products"]
        for name, data in events
        if name == "products"
    )

    response = client.post(
        f"/api/v1/chat/sessions/{session_id}/feedback-target",
        json={"conversation_version": 1},
    )

    assert response.status_code == 200
    assert response.json()["conversation_version"] == 1
    assert response.json()["displayed_product_ids"] == [
        item["id"] for item in products
    ]


def test_runtime_commit_failure_emits_one_error_without_feedback() -> None:
    from app.guide.adapters.state import InMemoryConversationState
    from app.guide_runtime.composition import (
        build_consultation_vertical_runtime,
    )

    class FailingConversationState(InMemoryConversationState):
        def __init__(self) -> None:
            super().__init__()
            self.save_calls = 0

        def save(self, snapshot, *, expected_version):
            del snapshot, expected_version
            self.save_calls += 1
            raise RuntimeError("conversation commit failed")

    class RecordingFeedback:
        def __init__(self) -> None:
            self.completions = []
            self.persisted = []

        def prepare_completed(self, *, actor, completion):
            del actor
            self.completions.append(completion)
            return SimpleNamespace(
                receipt=FeedbackTargetReceipt(
                    conversation_version=completion.conversation_version,
                    displayed_product_ids=tuple(
                        completion.card_display.visible_product_ids
                    ),
                    profile_version=None,
                )
            )

        def persist_prepared(self, prepared):
            self.persisted.append(prepared)
            return prepared.receipt

        def register_completed(self, *, actor, completion):
            prepared = self.prepare_completed(
                actor=actor,
                completion=completion,
            )
            return self.persist_prepared(prepared)

    state = FailingConversationState()
    feedback = RecordingFeedback()
    vertical = build_consultation_vertical_runtime(
        conversation_state=state,
        semantic_intent=exact_echo_understanding(),
    )
    payload = {
        "message": "500 元内敏感肌修护精华",
        "session_id": "runtime-commit-failure",
        "conversation_version": 0,
    }
    response = TestClient(
        create_app(
            consultation_runtime=vertical,
            feedback_service=feedback,
        )
    ).post(
        "/api/v1/chat/stream",
        json=payload,
    )
    events = _events(response)
    names = [name for name, _ in events]

    assert state.save_calls == 1
    assert state.load("runtime-commit-failure") is None
    assert names == ["start", "error"]
    assert events[-1][1] == {
        "error": "GUIDE_INTERNAL_ERROR",
        "message": "推荐暂时不可用，请稍后重试。",
    }
    assert feedback.completions == []
    assert feedback.persisted == []


def test_runtime_does_not_invoke_feedback_during_byte_forwarding() -> None:
    from app.guide.adapters.state import InMemoryConversationState
    from app.guide_runtime.composition import (
        build_consultation_vertical_runtime,
    )

    class CountingConversationState(InMemoryConversationState):
        def __init__(self) -> None:
            super().__init__()
            self.save_calls = 0

        def save(self, snapshot, *, expected_version):
            self.save_calls += 1
            return super().save(
                snapshot,
                expected_version=expected_version,
            )

    class FailingFeedback(_PreparedRecordingFeedback):
        def persist_prepared(self, prepared):
            self.persisted.append(prepared)
            raise OSError("feedback target persistence failed")

    state = CountingConversationState()
    feedback = FailingFeedback()
    vertical = build_consultation_vertical_runtime(
        conversation_state=state,
        semantic_intent=exact_echo_understanding(),
    )
    payload = {
        "message": "500 元内敏感肌修护精华",
        "session_id": "runtime-feedback-persist-failure",
        "conversation_version": 0,
    }
    response = TestClient(
        create_app(
            consultation_runtime=vertical,
            feedback_service=feedback,
        )
    ).post(
        "/api/v1/chat/stream",
        json=payload,
    )
    events = _events(response)
    names = [name for name, _ in events]
    snapshot = state.load(payload["session_id"])

    assert names[-1] == "end"
    assert "feedback_target" not in names
    assert "delivery_control" not in names
    assert state.save_calls == 1
    assert snapshot is not None
    assert snapshot.version == 1
    assert feedback.persisted == []


def test_static_product_image_is_served() -> None:
    client = TestClient(create_app())

    response = client.get(
        "/static/images/products/tmall_v3_746513552108.png"
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content.startswith(b"\x89PNG")


def test_stream_returns_locked_slice1_contract() -> None:
    client = TestClient(create_app())

    response = client.post(
        "/api/v1/chat/stream",
        json={
            "message": "500 内适合油敏肌的防晒",
            "session_id": "http-test",
            "stream": True,
        },
    )
    events = _events(response)
    names = [name for name, _ in events]

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert names[0] == "start"
    assert names[-1] == "end"
    assert names.count("end") == 1
    products = next(data for name, data in events if name == "products")
    card_display = next(
        data
        for name, data in events
        if name == "card_display_contract"
    )
    assert [item["id"] for item in products["products"]] == [101, 26, 52]
    assert card_display == {
        "mode": "recommendation",
        "visible_product_ids": [101, 26, 52],
        "max_cards": 3,
        "reason": "recommendation",
    }
    assert names.index("answer_contract") < names.index(
        "card_display_contract"
    )
    assert names.index("card_display_contract") < names.index("products")
    assert products["products"][0]["image_url"].startswith("/static/")
    assert products["products"][0]["detail_url"].startswith("https://")


def test_runtime_consultation_profile_vertical_uses_typed_zero_card_stages(
    tmp_path: Path,
) -> None:
    from app.guide_runtime.composition import (
        build_consultation_vertical_runtime,
    )
    from tests.guide.runtime.test_consultation_vertical_composition import (
        ConsultationTurnMeaningPort,
    )

    vertical = build_consultation_vertical_runtime(
        state_dir=tmp_path / "consultation-state",
        semantic_intent=ConsultationTurnMeaningPort(),
    )
    client = TestClient(
        create_app(
            consultation_runtime=vertical,
        )
    )
    session_id = "runtime-consultation-profile"
    version = 0
    for message, typed_event in zip(
        (
            "两颊干燥，T区不油，换季泛红，平时保湿不刺痛，现在也不疼",
            "我确认是干皮",
        ),
        (
            "consultation_provisional",
            "profile_confirmation",
        ),
        strict=True,
    ):
        events = _events(
            client.post(
                "/api/v1/chat/stream",
                json={
                    "message": message,
                    "session_id": session_id,
                    "conversation_version": version,
                },
            )
        )
        names = [name for name, _ in events]
        assert typed_event in names
        assert "products" not in names
        assert next(
            data
            for name, data in events
            if name == "card_display_contract"
        )["max_cards"] == 0
        version = events[-1][1]["conversation_version"]

    recommendation = _events(
        client.post(
            "/api/v1/chat/stream",
            json={
                "message": "500元内防晒",
                "session_id": session_id,
                "conversation_version": version,
            },
        )
    )
    assert "products" in [name for name, _ in recommendation]
    stored = vertical.conversation_state.load(session_id)
    assert stored is not None
    assert stored.recommendation_slot is not None
    assert stored.recommendation_slot.query_context.skin == "dry"


def test_runtime_stream_continues_active_stream_consultation(
    tmp_path: Path,
) -> None:
    from app.guide_runtime.composition import (
        build_consultation_vertical_runtime,
    )
    from tests.guide.runtime.test_consultation_vertical_composition import (
        ConsultationTurnMeaningPort,
    )

    vertical = build_consultation_vertical_runtime(
        state_dir=tmp_path / "consultation-state",
        semantic_intent=ConsultationTurnMeaningPort(),
    )
    client = TestClient(
        create_app(
            consultation_runtime=vertical,
        )
    )
    session_id = "runtime-consultation-stream-message-parity"
    entered = _events(
        client.post(
            "/api/v1/chat/stream",
            json={
                "message": (
                    "两颊干燥，T区不油，换季泛红，"
                    "平时保湿不刺痛，现在也不疼"
                ),
                "session_id": session_id,
                "conversation_version": 0,
            },
        )
    )
    assert entered[-1] == (
        "end",
        {"conversation_version": 1},
    )

    response = client.post(
        "/api/v1/chat/stream",
        json={
            "message": "我确认是干皮",
            "session_id": session_id,
            "conversation_version": 1,
        },
    )

    assert response.status_code == 200
    events = _events(response)
    assert next(
        data["intent"] for name, data in events if name == "intent"
    ) == "consultation_confirmation"
    assert any(name == "profile_confirmation" for name, _ in events)
    assert next(
        data["mode"]
        for name, data in events
        if name == "card_display_contract"
    ) == "none"
    assert "products" not in [name for name, _ in events]
    assert events[-1] == ("end", {"conversation_version": 2})


def test_stream_returns_locked_repair_serum_contract() -> None:
    client = TestClient(create_app())

    response = client.post(
        "/api/v1/chat/stream",
        json={
            "message": "500 元内敏感肌修护精华",
            "session_id": "serum-http-test",
            "stream": True,
        },
    )
    events = _events(response)
    products = next(data for name, data in events if name == "products")

    assert [item["id"] for item in products["products"]] == [38, 91]
    assert all(
        item["matched_efficacies"] == ["修护"]
        for item in products["products"]
    )
    assert all(
        item["suitable_skin"] == "肤质数据缺失"
        for item in products["products"]
    )


def test_session_delete_is_owner_scoped_idempotent_and_removes_state() -> None:
    runtime_app = create_app()
    owner_client = TestClient(runtime_app)
    foreign_client = TestClient(runtime_app)
    session_id = "runtime-delete-owned-session"
    response = owner_client.post(
        "/api/v1/chat/stream",
        json={
            "message": "干敏肌想要抗初老精华，预算1000左右",
            "session_id": session_id,
            "conversation_version": 0,
        },
    )
    assert response.status_code == 200
    state = runtime_app.state.orchestrator._conversation_state
    stored = state.load(session_id)
    assert stored is not None
    assert stored.reply_slot is not None

    foreign = foreign_client.delete(
        f"/api/v1/chat/sessions/{session_id}"
    )
    assert foreign.status_code == 204
    assert state.load(session_id) is not None

    deleted = owner_client.delete(
        f"/api/v1/chat/sessions/{session_id}"
    )
    assert deleted.status_code == 204
    assert state.load(session_id) is None

    repeated = owner_client.delete(
        f"/api/v1/chat/sessions/{session_id}"
    )
    assert repeated.status_code == 204


def test_runtime_stream_exposes_scenario_review_summary_and_pitfalls() -> None:
    client = TestClient(create_app())

    outdoor = _events(
        client.post(
            "/api/v1/chat/stream",
            json={
                "message": "500 元内长时间户外防晒",
                "session_id": "runtime-outdoor-scenario",
                "conversation_version": 0,
            },
        )
    )
    outdoor_names = [name for name, _ in outdoor]
    outdoor_products = next(
        data["products"]
        for name, data in outdoor
        if name == "products"
    )
    outdoor_reviews = next(
        data
        for name, data in outdoor
        if name == "review_evidence"
    )

    assert outdoor_names.index("scenario_evidence") < (
        outdoor_names.index("review_evidence")
    )
    assert outdoor_names.index("review_evidence") < (
        outdoor_names.index("pitfalls")
    )
    assert outdoor_names.index("pitfalls") < (
        outdoor_names.index("decision_process")
    )
    assert [item["id"] for item in outdoor_products] == [101, 26, 52]
    assert outdoor_reviews["approved_source_count"] == 6
    assert [
        item["product_id"] for item in outdoor_reviews["results"]
    ] == [101, 26, 52]
    assert [
        len(item["evidence"]) for item in outdoor_reviews["results"]
    ] == [0, 0, 0]
    assert outdoor_reviews["summaries"] == []

    sensitive = _events(
        client.post(
            "/api/v1/chat/stream",
            json={
                "message": "500 元内敏感期修护精华",
                "session_id": "runtime-sensitive-scenario",
                "conversation_version": 0,
            },
        )
    )
    sensitive_products = next(
        data["products"]
        for name, data in sensitive
        if name == "products"
    )
    sensitive_pitfalls = next(
        data["pitfalls"]
        for name, data in sensitive
        if name == "pitfalls"
    )

    assert [item["id"] for item in sensitive_products] == [38, 91]
    assert [item["product_id"] for item in sensitive_pitfalls] == [38, 91]
    assert all(item["evidence_refs"] for item in sensitive_pitfalls)


@pytest.mark.parametrize(
    (
        "followup",
        "expected_ids",
        "expected_mode",
        "expected_version",
    ),
    MULTITURN_CASES,
)
def test_runtime_http_supports_every_formal_multiturn_route(
    followup: str,
    expected_ids: list[int],
    expected_mode: str,
    expected_version: int,
    tmp_path: Path,
) -> None:
    from app.guide.understanding.turn_meaning_contracts import TurnMeaning
    from app.guide_runtime.composition import (
        build_consultation_vertical_runtime,
    )

    class FormalMultiturnMeaningPort:
        def propose(self, message, context):
            del context
            if message == "500 元内敏感肌修护精华":
                return TurnMeaning(
                    operation_hint="recommendation",
                    recommendation_mode="explore",
                    recommendation_mode_basis={
                        "basis": "bounded_exploration",
                        "source_text": "500 元内",
                    },
                    recommendation_count=None,
                    topic_hint="serum",
                    continuity_hint="new_task",
                    subject_scope_hint="self",
                    budget_candidates=(
                        {
                            "raw_text": "500 元内",
                            "relation": "maximum",
                            "minimum": None,
                            "maximum": "500",
                        },
                    ),
                    question_meaning=message,
                    safety_language="ordinary",
                )
            if message == "第二款呢":
                return TurnMeaning(
                    operation_hint="followup",
                    topic_hint=None,
                    continuity_hint="continue",
                    subject_scope_hint="self",
                    reference_mentions=(
                        {
                            "raw_text": "第二款",
                            "object_family_hint": "product",
                            "ordinal_hint": 2,
                            "plurality_hint": "single",
                        },
                    ),
                    question_meaning="继续查看第二款",
                    safety_language="ordinary",
                )
            if message == "哪个更便宜":
                return TurnMeaning(
                    operation_hint="comparison",
                    topic_hint=None,
                    continuity_hint="continue",
                    subject_scope_hint="self",
                    reference_mentions=(
                        {
                            "raw_text": "哪个",
                            "object_family_hint": "product",
                            "ordinal_hint": None,
                            "plurality_hint": "batch",
                            "batch_size_hint": 2,
                        },
                    ),
                    preference_candidates=(
                        {
                            "field_key": "reference_price",
                            "concept_id": None,
                            "raw_text": "更便宜",
                            "polarity": "prefer",
                            "strength": "ordinary",
                        },
                    ),
                    question_meaning="比较当前两款价格",
                    safety_language="ordinary",
                )
            assert message == "预算降到100元呢"
            return TurnMeaning(
                operation_hint="followup",
                topic_hint=None,
                continuity_hint="continue",
                subject_scope_hint="self",
                reference_mentions=(
                    {
                        "raw_text": "预算",
                        "object_family_hint": "constraint",
                        "ordinal_hint": None,
                        "plurality_hint": "single",
                    },
                ),
                budget_candidates=(
                    {
                        "raw_text": "100元",
                        "relation": "maximum",
                        "minimum": None,
                        "maximum": "100",
                    },
                ),
                question_meaning="把原推荐预算上限改为100元",
                safety_language="ordinary",
            )

    vertical = build_consultation_vertical_runtime(
        state_dir=tmp_path / f"formal-multiturn-{expected_mode}",
        semantic_intent=FormalMultiturnMeaningPort(),
    )
    client = TestClient(
        create_app(
            consultation_runtime=vertical,
        )
    )
    session_id = f"runtime-http-{followup}"
    first = client.post(
        "/api/v1/chat/stream",
        json={
            "message": "500 元内敏感肌修护精华",
            "session_id": session_id,
            "conversation_version": 0,
        },
    )
    first_events = _events(first)
    assert first_events[-1] == (
        "end",
        {"conversation_version": 1},
    )

    second = client.post(
        "/api/v1/chat/stream",
        json={
            "message": followup,
            "session_id": session_id,
            "conversation_version": 1,
        },
    )
    second_events = _events(second)
    products = next(
        data for name, data in second_events if name == "products"
    )
    presentation = next(
        data
        for name, data in second_events
        if name == "presentation_contract"
    )
    assert [
        item["id"]
        for item in products["products"]
    ] == expected_ids
    assert presentation["mode"] == expected_mode
    assert second_events[-1] == (
        "end",
        {"conversation_version": expected_version},
    )


@pytest.mark.parametrize(
    (
        "revision",
        "expected_ids",
        "expected_winner",
        "expected_version",
    ),
    SKIN_REVISION_CASES,
)
def test_runtime_http_supports_skin_revision(
    revision: str,
    expected_ids: list[int],
    expected_winner: str,
    expected_version: int,
    tmp_path: Path,
) -> None:
    from app.guide.understanding.turn_meaning_contracts import TurnMeaning
    from app.guide_runtime.composition import (
        build_consultation_vertical_runtime,
    )

    class SkinRevisionMeaningPort:
        def propose(self, message, context):
            del context
            if message == "500 元内修护精华":
                return TurnMeaning(
                    operation_hint="recommendation",
                    recommendation_mode="explore",
                    recommendation_mode_basis={
                        "basis": "bounded_exploration",
                        "source_text": "500 元内",
                    },
                    recommendation_count=None,
                    topic_hint="serum",
                    continuity_hint="new_task",
                    subject_scope_hint="self",
                    budget_candidates=(
                        {
                            "raw_text": "500 元内",
                            "relation": "maximum",
                            "minimum": None,
                            "maximum": "500",
                        },
                    ),
                    question_meaning=message,
                    safety_language="ordinary",
                )
            assert message == revision
            return TurnMeaning(
                operation_hint="followup",
                topic_hint=None,
                continuity_hint="continue",
                subject_scope_hint="self",
                reference_mentions=(
                    {
                        "raw_text": "敏感肌",
                        "object_family_hint": "constraint",
                        "ordinal_hint": None,
                        "plurality_hint": "single",
                    },
                ),
                constraint_changes=(
                    {
                        "parent_concept": "skin",
                        "requested_change": "replace",
                        "raw_text": "改成敏感肌",
                        "normalized_value": "sensitive",
                    },
                ),
                question_meaning=message,
                safety_language="ordinary",
            )

    vertical = build_consultation_vertical_runtime(
        state_dir=tmp_path / "skin-revision-state",
        semantic_intent=SkinRevisionMeaningPort(),
    )
    client = TestClient(
        create_app(
            consultation_runtime=vertical,
        )
    )
    session_id = f"runtime-skin-revision-{revision}"
    first = client.post(
        "/api/v1/chat/stream",
        json={
            "message": "500 元内修护精华",
            "session_id": session_id,
            "conversation_version": 0,
        },
    )
    assert _events(first)[-1] == (
        "end",
        {"conversation_version": 1},
    )

    second = client.post(
        "/api/v1/chat/stream",
        json={
            "message": revision,
            "session_id": session_id,
            "conversation_version": 1,
        },
    )
    events = _events(second)
    products = next(
        data for name, data in events if name == "products"
    )
    decision = next(
        data
        for name, data in events
        if name == "decision_process"
    )

    assert [
        item["id"] for item in products["products"]
    ] == expected_ids
    assert decision["winner_status"] == expected_winner
    assert events[-1] == (
        "end",
        {"conversation_version": expected_version},
    )


def test_http_round_trips_budget_revision_context(
    tmp_path: Path,
) -> None:
    from app.guide.understanding.turn_meaning_contracts import TurnMeaning
    from app.guide_runtime.composition import (
        build_consultation_vertical_runtime,
    )

    class BudgetRevisionMeaningPort:
        def propose(self, message, context):
            del context
            if message == "500 元内敏感肌修护精华":
                return TurnMeaning(
                    operation_hint="recommendation",
                    recommendation_mode="explore",
                    recommendation_mode_basis={
                        "basis": "bounded_exploration",
                        "source_text": "500 元内",
                    },
                    recommendation_count=None,
                    topic_hint="serum",
                    continuity_hint="new_task",
                    subject_scope_hint="self",
                    budget_candidates=(
                        {
                            "raw_text": "500 元内",
                            "relation": "maximum",
                            "minimum": None,
                            "maximum": "500",
                        },
                    ),
                    question_meaning=message,
                    safety_language="ordinary",
                )
            assert message == "预算降到 100 元呢"
            return TurnMeaning(
                operation_hint="followup",
                topic_hint=None,
                continuity_hint="continue",
                subject_scope_hint="self",
                reference_mentions=(
                    {
                        "raw_text": "预算",
                        "object_family_hint": "constraint",
                        "ordinal_hint": None,
                        "plurality_hint": "single",
                    },
                ),
                budget_candidates=(
                    {
                        "raw_text": "100 元",
                        "relation": "maximum",
                        "minimum": None,
                        "maximum": "100",
                    },
                ),
                question_meaning="把原推荐预算上限改为100元",
                safety_language="ordinary",
            )

    vertical = build_consultation_vertical_runtime(
        state_dir=tmp_path / "budget-revision-state",
        semantic_intent=BudgetRevisionMeaningPort(),
    )
    client = TestClient(
        create_app(
            consultation_runtime=vertical,
        )
    )
    first = client.post(
        "/api/v1/chat/stream",
        json={
            "message": "500 元内敏感肌修护精华",
            "session_id": "budget-revision-http",
            "conversation_version": 0,
        },
    )
    assert _events(first)[-1] == (
        "end",
        {"conversation_version": 1},
    )

    second = client.post(
        "/api/v1/chat/stream",
        json={
            "message": "预算降到 100 元呢",
            "session_id": "budget-revision-http",
            "conversation_version": 1,
        },
    )
    events = _events(second)
    products = next(
        data for name, data in events if name == "products"
    )
    decision = next(
        data
        for name, data in events
        if name == "decision_process"
    )
    presentation = next(
        data
        for name, data in events
        if name == "presentation_contract"
    )

    assert [item["id"] for item in products["products"]] == [91]
    assert decision["winner_status"] == "INSUFFICIENT_FOR_WINNER"
    assert any(
        section.get("copy_text")
        for section in presentation["sections"]
    )
    assert "message" not in {name for name, _ in events}
    assert events[-1] == (
        "end",
        {"conversation_version": 2},
    )


def test_http_client_cannot_override_server_query_context(
    tmp_path: Path,
) -> None:
    from app.guide.understanding.turn_meaning_contracts import TurnMeaning
    from app.guide_runtime.composition import (
        build_consultation_vertical_runtime,
    )

    class BudgetRevisionMeaningPort:
        def propose(self, message, context):
            del context
            if message == "500 元内敏感肌修护精华":
                return TurnMeaning(
                    operation_hint="recommendation",
                    recommendation_mode="explore",
                    recommendation_mode_basis={
                        "basis": "bounded_exploration",
                        "source_text": "500 元内",
                    },
                    topic_hint="serum",
                    continuity_hint="new_task",
                    subject_scope_hint="self",
                    budget_candidates=(
                        {
                            "raw_text": "500 元内",
                            "relation": "maximum",
                            "minimum": None,
                            "maximum": "500",
                        },
                    ),
                    question_meaning=message,
                    safety_language="ordinary",
                )
            return TurnMeaning(
                operation_hint="followup",
                topic_hint=None,
                continuity_hint="continue",
                subject_scope_hint="self",
                reference_mentions=(
                    {
                        "raw_text": "预算",
                        "object_family_hint": "constraint",
                        "ordinal_hint": None,
                        "plurality_hint": "single",
                    },
                ),
                budget_candidates=(
                    {
                        "raw_text": "100元",
                        "relation": "maximum",
                        "minimum": None,
                        "maximum": "100",
                    },
                ),
                question_meaning=message,
                safety_language="ordinary",
            )

    vertical = build_consultation_vertical_runtime(
        state_dir=tmp_path / "server-owned-state",
        semantic_intent=BudgetRevisionMeaningPort(),
    )
    client = TestClient(
        create_app(
            consultation_runtime=vertical,
        )
    )
    client.post(
        "/api/v1/chat/stream",
        json={
            "message": "500 元内敏感肌修护精华",
            "session_id": "server-owned-context",
            "conversation_version": 0,
        },
    )

    response = client.post(
        "/api/v1/chat/stream",
        json={
            "message": "预算降到100元呢",
            "session_id": "server-owned-context",
            "conversation_version": 1,
            "query_context": {
                "category": "sunscreen",
                "budget_maximum": 1,
            },
        },
    )
    assert response.status_code == 422


def test_runtime_app_instances_share_conversation_state() -> None:
    first = TestClient(create_app())
    initial = first.post(
        "/api/v1/chat/stream",
        json={
            "message": "500 元内敏感肌修护精华",
            "session_id": "isolated-session",
            "conversation_version": 0,
        },
    )
    second = TestClient(create_app())
    second.cookies.update(first.cookies)
    response = second.post(
        "/api/v1/chat/stream",
        json={
            "message": "第二款呢",
            "session_id": "isolated-session",
            "conversation_version": 1,
        },
    )
    events = _events(response)
    products = next(
        data["products"]
        for name, data in events
        if name == "products"
    )

    assert _events(initial)[-1] == (
        "end",
        {"conversation_version": 1},
    )
    assert [product["id"] for product in products] == [91]
    assert events[-1] == (
        "end",
        {"conversation_version": 2},
    )


def test_standalone_runtime_persists_first_clarification_turn() -> None:
    response = TestClient(create_app()).post(
        "/api/v1/chat/stream",
        json={
            "message": "第二款呢",
            "session_id": "runtime-owner-gate-exempt",
            "conversation_version": 0,
        },
    )
    events = _events(response)
    clarification = next(
        data for name, data in events if name == "clarify"
    )

    assert clarification["question"] == (
        "请明确这次指的是哪一款商品。"
    )
    assert events[-1] == (
        "end",
        {"conversation_version": 1},
    )


def test_image_request_is_publicly_rejected_without_legacy_fallback() -> None:
    client = TestClient(create_app())

    response = client.post(
        "/api/v1/chat/stream",
        json={
            "message": "这张图适合敏感肌吗",
            "session_id": "image-test",
            "stream": True,
            "image_results": [{"product_id": "55"}],
        },
    )
    assert response.status_code == 422


def test_invalid_budget_is_visible_clarification() -> None:
    client = TestClient(create_app())

    response = client.post(
        "/api/v1/chat/stream",
        json={
            "message": "0 元以内的防晒",
            "session_id": "invalid-budget",
            "stream": True,
        },
    )
    events = _events(response)
    names = [name for name, _ in events]

    assert names[-1] == "end"
    assert "products" not in names
    clarification = next(
        data for name, data in events if name == "clarify"
    )
    assert clarification["question"].strip()


def test_public_error_is_terminal_and_hides_internal_detail() -> None:
    from app.guide.application.public_event_envelope import (
        materialize_error_frames,
    )
    from app.guide_runtime.sse import iter_http_events

    class PublicErrorOrchestrator:
        def stream(self, turn):
            yield from materialize_error_frames(
                session_id=turn.session_id,
                code="GUIDE_INTERNAL_ERROR",
                message="推荐暂时不可用，请稍后重试。",
            )

    frames = tuple(
        iter_http_events(
            PublicErrorOrchestrator(),
            ChatStreamRequest.model_validate(
                {
                    "message": "500 内适合油敏肌的防晒",
                    "session_id": "error-test",
                    "stream": True,
                },
                strict=True,
            ),
        )
    )
    events = _events(
        SimpleNamespace(text=b"".join(frames).decode("utf-8"))
    )

    assert [name for name, _ in events] == ["start", "error"]
    assert "end" not in [name for name, _ in events]
    assert events[-1][1] == {
        "error": "GUIDE_INTERNAL_ERROR",
        "message": "推荐暂时不可用，请稍后重试。",
    }


def test_app_uses_unified_flow_from_injected_vertical_runtime() -> None:
    service = ImageBundleService(
        state=InMemoryImageBundleState(max_bundles=4)
    )
    vertical = _image_guide_runtime(service)

    app = create_app(
        consultation_runtime=vertical,
        image_bundle_service=service,
    )

    assert app.state.orchestrator is vertical.unified


@pytest.mark.parametrize("count", IMAGE_UPLOAD_COUNTS)
def test_runtime_image_upload_reuses_formal_count_matrix(
    count: int,
) -> None:
    client = TestClient(create_app())

    receipt = _upload_bundle(
        client,
        session_id=f"runtime-image-count-{count}",
        count=count,
    )

    assert receipt["version"] == 1
    assert receipt["image_count"] == count
    assert receipt["message"] == (
        "图片已安全接收，发送后将进行单图相似检索。"
    )
    assert "owner_token_sha256" not in receipt
    assert "images" not in receipt
    assert "candidates" not in receipt


@pytest.mark.parametrize(
    ("session_id", "expected_status"),
    [("s" * 100, 201), ("s" * 101, 422), ("   ", 422)],
)
def test_runtime_image_upload_matches_chat_session_id_boundary(
    session_id: str,
    expected_status: int,
) -> None:
    response = TestClient(create_app()).post(
        "/api/v1/chat/image-bundles",
        data={"session_id": session_id},
        files=[
            (
                "images",
                ("product.jpg", _jpeg(), "image/jpeg"),
            )
        ],
    )

    assert response.status_code == expected_status


def test_runtime_two_image_stream_emits_exact_ordered_comparison() -> None:
    client = _image_client(product_ids=(53, 55))
    session_id = "runtime-image-chat"
    receipt = _upload_bundle(client, session_id=session_id, count=2)

    response = client.post(
        "/api/v1/chat/stream",
        json={
            "message": "",
            "image_action": "compare",
            "session_id": session_id,
            "conversation_version": 0,
            "image_bundle_id": receipt["bundle_id"],
            "image_bundle_version": receipt["version"],
            "image_bundle_token": receipt["owner_token"],
        },
    )

    events = _events(response)
    names = [name for name, _ in events]
    observations = [
        data["observation"]
        for name, data in events
        if name == "image_observation"
    ]
    contract = next(
        data
        for name, data in events
        if name == "card_display_contract"
    )
    product_event = next(
        data for name, data in events if name == "products"
    )
    presentation = next(
        data for name, data in events if name == "presentation_contract"
    )
    products = product_event["products"]

    assert names.count("image_observation") == 2
    assert [item["confirmed_product_id"] for item in observations] == [53, 55]
    assert next(data for name, data in events if name == "intent")[
        "intent"
    ] == "image_compare"
    decision = next(
        data for name, data in events if name == "decision_process"
    )
    assert decision["ordered_product_ids"] == [53, 55]
    assert (
        decision["comparison_data"]["status"]
        == "insufficient_evidence"
    )
    assert decision["comparison_data"]["winner_reference"] is None
    assert decision["winner_status"] == "insufficient_evidence"
    assert next(
        data for name, data in events if name == "answer_contract"
    )["winner_status"] == "insufficient_evidence"
    assert contract == {
        "mode": "comparison",
        "visible_product_ids": [53, 55],
        "max_cards": 2,
        "reason": "comparison",
    }
    assert [product["id"] for product in products] == [53, 55]
    assert presentation["mode"] == "comparison"
    assert presentation["winner"]["status"] == "insufficient"
    assert presentation["winner"]["winner_product_id"] is None
    assert presentation["winner"]["fact_ids"] == []
    assert all(product["matched_efficacies"] == [] for product in products)
    assert all(
        product["suitable_skin"] == "肤质数据缺失"
        for product in products
    )
    assert all(
        card["skin_match"] == "unknown"
        for card in product_event["cards"]
    )
    assert names[-1] == "end"
    assert receipt["owner_token"] not in response.text


def test_non_stream_chat_message_route_is_absent() -> None:
    app = create_app()
    assert not any(
        getattr(route, "path", None) == "/api/v1/chat/message"
        and "POST" in getattr(route, "methods", set())
        for route in app.routes
    )
    client = TestClient(app)
    response = client.post(
        "/api/v1/chat/message",
        json={
            "message": "推荐防晒",
            "session_id": "runtime-message-route-absent",
            "conversation_version": 0,
        },
    )

    assert response.status_code == 404


@pytest.mark.parametrize(
    "override",
    [
        {"session_id": "runtime-image-foreign"},
        {
            "image_bundle_token": (
                "owner_wrong-token-value-with-enough-entropy-123456"
            )
        },
        {"image_bundle_version": 2},
        {
            "image_bundle_id": (
                "bundle_unknown-token-value-with-enough-entropy"
            )
        },
    ],
)
def test_runtime_image_chat_reuses_fail_closed_matrix(
    override: dict[str, Any],
) -> None:
    client = _image_client()
    session_id = "runtime-image-owner"
    receipt = _upload_bundle(client, session_id=session_id)
    payload = {
        "message": "看看图片",
        "session_id": session_id,
        "conversation_version": 0,
        "image_bundle_id": receipt["bundle_id"],
        "image_bundle_version": receipt["version"],
        "image_bundle_token": receipt["owner_token"],
    }
    payload.update(override)

    events = _events(
        client.post("/api/v1/chat/stream", json=payload)
    )

    assert events == [
        ("start", {"session_id": payload["session_id"]}),
        (
            "error",
            {
                "error": "IMAGE_BUNDLE_UNAVAILABLE",
                "message": "图片引用不可用，请重新上传。",
            },
        ),
    ]


def test_runtime_rejects_partial_reference_and_legacy_candidate_facts(
) -> None:
    client = TestClient(create_app())
    partial = client.post(
        "/api/v1/chat/stream",
        json={
            "message": "看看图片",
            "session_id": "runtime-partial-image",
            "conversation_version": 0,
            "image_bundle_id": "bundle_" + "a" * 32,
        },
    )
    injected = client.post(
        "/api/v1/chat/stream",
        json={
            "message": "看看图片",
            "session_id": "runtime-injected-image",
            "conversation_version": 0,
            "image_results": [{"product_id": 55, "winner": True}],
        },
    )

    assert partial.status_code == 422
    assert injected.status_code == 422


def test_runtime_delete_prevents_bundle_replay() -> None:
    client = _image_client()
    session_id = "runtime-image-delete"
    receipt = _upload_bundle(client, session_id=session_id)

    deleted = client.request(
        "DELETE",
        f"/api/v1/chat/image-bundles/{receipt['bundle_id']}",
        json={
            "session_id": session_id,
            "version": receipt["version"],
            "owner_token": receipt["owner_token"],
        },
    )
    replay = client.post(
        "/api/v1/chat/stream",
        json={
            "message": "再次使用图片",
            "session_id": session_id,
            "conversation_version": 0,
            "image_bundle_id": receipt["bundle_id"],
            "image_bundle_version": receipt["version"],
            "image_bundle_token": receipt["owner_token"],
        },
    )

    assert deleted.status_code == 204
    assert _events(replay)[-1] == (
        "error",
        {
            "error": "IMAGE_BUNDLE_UNAVAILABLE",
            "message": "图片引用不可用，请重新上传。",
        },
    )


def test_runtime_app_instances_share_image_bundle_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("XIAORO_GUIDE_STATE_DIR", str(tmp_path))
    first_service = build_image_bundle_service()
    second_service = build_image_bundle_service()
    first_runtime = _image_guide_runtime(first_service)
    second_runtime = _image_guide_runtime(second_service)
    first = TestClient(
        create_app(
            consultation_runtime=first_runtime,
            image_bundle_service=first_service,
        )
    )
    second = TestClient(
        create_app(
            consultation_runtime=second_runtime,
            image_bundle_service=second_service,
        )
    )
    session_id = "shared-image-bundle"
    receipt = _upload_bundle(first, session_id=session_id)

    response = second.post(
        "/api/v1/chat/stream",
        json={
            "message": "",
            "image_action": "identify",
            "session_id": session_id,
            "conversation_version": 0,
            "image_bundle_id": receipt["bundle_id"],
            "image_bundle_version": receipt["version"],
            "image_bundle_token": receipt["owner_token"],
        },
    )

    events = _events(response)
    observation = next(
        data for name, data in events if name == "image_observation"
    )
    products = next(data for name, data in events if name == "products")
    assert observation["observation"]["confirmed_product_id"] == 53
    assert products["products"]


def test_runtime_image_bundle_upload_and_authorize_across_processes(
    tmp_path: Path,
) -> None:
    context = multiprocessing.get_context("spawn")
    queue = context.Queue()
    state_directory = str(tmp_path / "shared-state")
    upload = context.Process(
        target=_multiprocess_runtime_upload,
        args=(state_directory, queue),
    )
    upload.start()
    receipt = queue.get(timeout=10)
    upload.join(timeout=10)
    assert upload.exitcode == 0

    authorize = context.Process(
        target=_multiprocess_runtime_authorize,
        args=(state_directory, receipt, 0, queue),
    )
    authorize.start()
    events = queue.get(timeout=10)
    authorize.join(timeout=10)
    queue.close()
    queue.join_thread()

    assert authorize.exitcode == 0
    assert events[0] == (
        "start",
        {"session_id": "multiprocess-image-owner"},
    )
    assert any(name == "image_observation" for name, _ in events)
    assert any(name == "products" for name, _ in events)

    delete_queue = context.Queue()
    delete = context.Process(
        target=_multiprocess_runtime_delete,
        args=(state_directory, receipt, delete_queue),
    )
    delete.start()
    deleted_status = delete_queue.get(timeout=10)
    delete.join(timeout=10)
    delete_queue.close()
    delete_queue.join_thread()
    assert delete.exitcode == 0
    assert deleted_status == 204

    replay_queue = context.Queue()
    replay = context.Process(
        target=_multiprocess_runtime_authorize,
        args=(state_directory, receipt, 1, replay_queue),
    )
    replay.start()
    replay_events = replay_queue.get(timeout=10)
    replay.join(timeout=10)
    replay_queue.close()
    replay_queue.join_thread()
    assert replay.exitcode == 0
    assert replay_events[-1] == (
        "error",
        {
            "error": "IMAGE_BUNDLE_UNAVAILABLE",
            "message": "图片引用不可用，请重新上传。",
        },
    )


def test_shared_bundle_state_uses_private_sqlite_and_hash_only_owner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_directory = tmp_path / "private-state"
    monkeypatch.setenv(
        "XIAORO_GUIDE_STATE_DIR",
        str(state_directory),
    )
    receipt = _upload_bundle(
        TestClient(create_app()),
        session_id="sqlite-owner-hash",
    )
    database_path = state_directory / "image_bundles.sqlite3"

    assert database_path.is_file()
    assert stat.S_IMODE(state_directory.stat().st_mode) == 0o700
    assert stat.S_IMODE(database_path.stat().st_mode) == 0o600
    with sqlite3.connect(database_path) as connection:
        stored_hash, bundle_json = connection.execute(
            """
            SELECT owner_token_sha256, bundle_json
            FROM image_bundles
            WHERE bundle_id = ?
            """,
            (receipt["bundle_id"],),
        ).fetchone()

    expected_hash = hashlib.sha256(
        receipt["owner_token"].encode("utf-8")
    ).hexdigest()
    assert stored_hash == expected_hash
    assert receipt["owner_token"] not in bundle_json
    assert expected_hash in bundle_json


def test_shared_bundle_state_cas_is_atomic_across_processes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_directory = str(tmp_path / "cas-state")
    monkeypatch.setenv("XIAORO_GUIDE_STATE_DIR", state_directory)
    receipt = _upload_bundle(
        TestClient(create_app()),
        session_id="multiprocess-cas-owner",
    )
    context = multiprocessing.get_context("spawn")
    start = context.Event()
    queue = context.Queue()
    processes = [
        context.Process(
            target=_multiprocess_bundle_cas,
            args=(
                state_directory,
                receipt["bundle_id"],
                start,
                queue,
            ),
        )
        for _ in range(2)
    ]
    for process in processes:
        process.start()
    ready = [queue.get(timeout=10), queue.get(timeout=10)]
    assert ready == [("ready", True), ("ready", True)]
    start.set()
    results = sorted(
        [queue.get(timeout=10)[1], queue.get(timeout=10)[1]]
    )
    for process in processes:
        process.join(timeout=10)
    queue.close()
    queue.join_thread()

    assert [process.exitcode for process in processes] == [0, 0]
    assert results == ["ImageBundleStateConflict", "saved"]
