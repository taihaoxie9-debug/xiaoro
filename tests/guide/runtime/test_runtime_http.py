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
from app.guide.feedback.delivery import FeedbackTargetReceipt
from app.guide.presentation.sse_events import (
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
    build_image_recommendation_orchestrator,
    guide_image_runtime_lock,
)
from app.guide_runtime.contracts import ChatStreamRequest
from app.guide_runtime.image_runtime import ImageRuntimeHealth
from tests.guide.semantic_test_port import (
    ExactEchoSemanticPort,
    exact_echo_understanding,
)


MULTITURN_CASES = (
    ("第二款呢", [91], 2),
    ("哪个更便宜", [91], 2),
    ("预算降到100元呢", [91], 2),
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


@pytest.fixture(autouse=True)
def _isolate_guide_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "GUIDE_UNIFIED_ROUTER_ENABLED",
        "false",
    )
    monkeypatch.setenv(
        "XIAORO_GUIDE_STATE_DIR",
        str(tmp_path / "guide-state"),
    )
    from app.guide_runtime import app as app_module
    from app.guide_runtime import composition

    real_build_runtime = composition.build_runtime_orchestrator
    real_build_consultation = (
        composition.build_consultation_vertical_runtime
    )
    real_compose_text = (
        composition.compose_text_recommendation_orchestrator
    )

    def build_runtime(*args, **kwargs):
        kwargs.setdefault("semantic_intent", ExactEchoSemanticPort())
        return real_build_runtime(*args, **kwargs)

    def build_consultation(*args, **kwargs):
        kwargs.setdefault("semantic_intent", ExactEchoSemanticPort())
        return real_build_consultation(*args, **kwargs)

    def compose_text(*args, **kwargs):
        kwargs.setdefault("understanding", exact_echo_understanding())
        return real_compose_text(*args, **kwargs)

    monkeypatch.setattr(
        composition,
        "build_runtime_orchestrator",
        build_runtime,
    )
    monkeypatch.setattr(
        composition,
        "build_consultation_vertical_runtime",
        build_consultation,
    )
    monkeypatch.setattr(
        composition,
        "compose_text_recommendation_orchestrator",
        compose_text,
    )
    monkeypatch.setattr(
        app_module,
        "build_runtime_orchestrator",
        build_runtime,
    )
    monkeypatch.setattr(
        app_module,
        "build_consultation_vertical_runtime",
        build_consultation,
    )


def _events(response) -> list[tuple[str, dict]]:
    blocks = [
        block
        for block in response.text.split("\n\n")
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
    client = TestClient(create_app(orchestrator=object()))
    result_queue.put(
        _upload_bundle(
            client,
            session_id="multiprocess-image-owner",
        )
    )


def _multiprocess_runtime_authorize(
    state_directory: str,
    receipt: dict[str, Any],
    result_queue,
) -> None:
    os.environ["XIAORO_GUIDE_STATE_DIR"] = state_directory
    service = build_image_bundle_service()
    response = TestClient(
        create_app(
            orchestrator=object(),
            image_bundle_service=service,
            image_runtime=_static_image_runtime(service),
        )
    ).post(
        "/api/v1/chat/stream",
        json={
            "message": "跨 worker 使用图片",
            "session_id": "multiprocess-image-owner",
            "conversation_version": 0,
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
    response = TestClient(
        create_app(orchestrator=object())
    ).request(
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


class StaticImageRuntime:
    def __init__(self, orchestrator: object) -> None:
        self.orchestrator = orchestrator
        lock = guide_image_runtime_lock()
        self._health = ImageRuntimeHealth(
            healthy=True,
            issues=(),
            model_name=lock.model_name,
            preprocessing_version=lock.preprocessing_version,
            index_sha256=lock.index_sha256,
        )

    def health(self) -> ImageRuntimeHealth:
        return self._health

    def get_orchestrator(self):
        return self.orchestrator


class MissingEndImageOrchestrator:
    def stream(self, turn):
        yield StartEvent(data=StartData(session_id=turn.session_id))
        yield IntentEvent(data=IntentData(mode="clarify"))
        yield MessageEvent(data=MessageData(content="incomplete"))


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
    assert_uncommitted,
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
    assert_uncommitted()
    assert terminal.index(b"event: feedback_target\n") < terminal.index(
        b"event: end\n"
    )

    if outcome == "send_error":
        release_terminal.set()
        result = await asyncio.gather(task, return_exceptions=True)
        assert isinstance(result[0], BaseException)
        assert_uncommitted()
        return sent
    if outcome == "disconnect":
        allow_disconnect.set()
        await asyncio.wait_for(task, timeout=10)
        assert_uncommitted()
        return sent

    release_terminal.set()
    await asyncio.wait_for(eof_entered.wait(), timeout=10)
    assert_committed()
    release_eof.set()
    await asyncio.wait_for(task, timeout=10)
    assert_committed()
    return sent


def _static_image_runtime(
    service: ImageBundleService,
    *,
    product_ids: tuple[int, ...] = (53,),
) -> StaticImageRuntime:
    from tests.guide.runtime.test_composition import StoredVectorEncoder

    return StaticImageRuntime(
        build_image_recommendation_orchestrator(
            repo_root=REPO_ROOT,
            image_bundle_service=service,
            encoder=StoredVectorEncoder(product_ids),
        )
    )


def _image_client(
    *,
    product_ids: tuple[int, ...] = (53,),
) -> TestClient:
    service = ImageBundleService(
        state=InMemoryImageBundleState(max_bundles=32)
    )
    return TestClient(
        create_app(
            image_bundle_service=service,
            image_runtime=_static_image_runtime(
                service,
                product_ids=product_ids,
            ),
        )
    )


def test_health_and_page_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(
        "GUIDE_UNIFIED_ROUTER_ENABLED",
        raising=False,
    )
    client = TestClient(
        create_app(image_runtime=StaticImageRuntime(object()))
    )
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
        "profile_state": "sqlite_fill_only_cas",
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
    client = TestClient(create_app(orchestrator=object()))

    response = client.get("/demo")

    assert response.status_code == 200
    assert "演示体验版" in response.text
    assert "/chat" in response.text
    assert "不计入最终验收" in response.text
    assert "no-store" in response.headers["cache-control"]


def test_health_exposes_unified_router_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GUIDE_UNIFIED_ROUTER_ENABLED", "true")
    client = TestClient(
        create_app(image_runtime=StaticImageRuntime(object()))
    )

    health = client.get("/health")

    assert health.status_code == 200
    assert health.json()["turn_router"] == "unified_v1"


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
            image_runtime=StaticImageRuntime(object()),
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
    assert stored.focus_state is not None
    assert stored.focus_state.active_processor == "recommendation"


def test_unified_router_switches_from_consultation_to_recommendation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app.guide_runtime.composition import (
        build_consultation_vertical_runtime,
    )

    monkeypatch.setenv("GUIDE_UNIFIED_ROUTER_ENABLED", "true")
    vertical = build_consultation_vertical_runtime(
        state_dir=tmp_path / "unified-switch-state",
    )
    client = TestClient(
        create_app(
            consultation_runtime=vertical,
            image_runtime=StaticImageRuntime(object()),
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
    assert stored.consultation is not None
    assert stored.focus_state is not None
    assert stored.focus_state.active_processor == "recommendation"


def test_unified_router_owns_image_turn_before_legacy_image_stream(
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

    class LegacyImageMustNotRun:
        def stream(self, turn):
            del turn
            raise AssertionError(
                "unified image turn entered legacy stream"
            )

    class RecordingUnified:
        def __init__(self) -> None:
            self.calls = []

        def stream_image(self, turn, *, image_processor):
            self.calls.append((turn, image_processor))
            yield StartEvent(
                data=StartData(session_id=turn.session_id)
            )
            yield IntentEvent(data=IntentData(mode="clarify"))
            yield ClarifyEvent(
                data=ClarifyData(
                    question="请补一张更清晰的正面图。",
                    clarification_code=ClarificationCode.REFERENCE,
                )
            )
            yield EndEvent(
                data=EndData(
                    conversation_version=turn.conversation_version
                )
            )

    owner = ProfileOwnerRef(
        scope="anonymous_browser",
        subject_id="runtime_unified_image_owner_0123456789",
    )
    unified = RecordingUnified()
    image = LegacyImageMustNotRun()
    runtime = SimpleNamespace(
        unified=unified,
        profile_owner=lambda session_id: owner,
    )
    service = ImageBundleService(
        state=InMemoryImageBundleState(max_bundles=8)
    )
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
            object(),
            payload,
            service,
            image_runtime=StaticImageRuntime(image),
            consultation_runtime=runtime,
            profile_owner=owner,
            unified_router_enabled=True,
        )
    )

    assert [name for name, _ in events] == [
        "start",
        "intent",
        "message",
        "end",
    ]
    assert len(unified.calls) == 1
    assert unified.calls[0][1] is image


def test_unified_router_real_image_persists_confirmed_focus(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app.guide_runtime.composition import (
        build_consultation_vertical_runtime,
    )
    from tests.guide.runtime.test_composition import StoredVectorEncoder

    monkeypatch.setenv("GUIDE_UNIFIED_ROUTER_ENABLED", "true")
    state_root = tmp_path / "unified-image-state"
    service = build_image_bundle_service(
        database_path=state_root / "image-bundles.sqlite3"
    )
    vertical = build_consultation_vertical_runtime(
        state_dir=state_root,
    )
    image = build_image_recommendation_orchestrator(
        repo_root=REPO_ROOT,
        image_bundle_service=service,
        consultation_runtime=vertical,
        encoder=StoredVectorEncoder(53),
    )
    client = TestClient(
        create_app(
            consultation_runtime=vertical,
            image_bundle_service=service,
            image_runtime=StaticImageRuntime(image),
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
    assert presentation["mode"] == "image_recommendation"
    assert 53 not in {item["id"] for item in products}
    assert events[-1] == ("end", {"conversation_version": 1})
    stored = vertical.conversation_state.load(session_id)
    assert stored is not None
    assert stored.focus_state is not None
    assert stored.focus_state.active_processor == "recommendation"
    assert [
        item.product_id
        for item in stored.focus_state.confirmed_image_products
    ] == [53]


def test_unified_router_two_images_use_standard_comparison(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app.guide.intent.executable_intent_compiler import (
        compile_turn_meaning,
    )
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
            return meaning, compile_turn_meaning(
                message=message,
                meaning=meaning,
                context=context,
            )

    monkeypatch.setenv("GUIDE_UNIFIED_ROUTER_ENABLED", "true")
    state_root = tmp_path / "unified-image-comparison-state"
    service = build_image_bundle_service(
        database_path=state_root / "image-bundles.sqlite3"
    )
    vertical = build_consultation_vertical_runtime(
        state_dir=state_root,
    )
    vertical.unified._understanding = ComparisonTranslator()
    image = build_image_recommendation_orchestrator(
        repo_root=REPO_ROOT,
        image_bundle_service=service,
        consultation_runtime=vertical,
        encoder=StoredVectorEncoder((53, 55)),
    )
    client = TestClient(
        create_app(
            consultation_runtime=vertical,
            image_bundle_service=service,
            image_runtime=StaticImageRuntime(image),
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
    assert stored.focus_state is not None
    assert stored.focus_state.active_processor == "comparison"
    assert [
        item.product_id
        for item in stored.focus_state.confirmed_image_products
    ] == [53, 55]


def test_runtime_single_image_sse_returns_real_cards_and_versions(
    tmp_path: Path,
) -> None:
    from tests.guide.runtime.test_composition import StoredVectorEncoder

    service = build_image_bundle_service(
        database_path=tmp_path / "image-bundles.sqlite3"
    )
    orchestrator = build_image_recommendation_orchestrator(
        repo_root=REPO_ROOT,
        image_bundle_service=service,
        encoder=StoredVectorEncoder(53),
    )
    client = TestClient(
        create_app(
            image_bundle_service=service,
            image_runtime=StaticImageRuntime(orchestrator),
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
    assert [product["id"] for product in products] == [54]
    assert all(product["image_url"] for product in products)
    assert all(product["detail_url"] for product in products)
    assert "图片已安全接收，识别尚未启用。" not in response.text


def test_runtime_image_profile_mismatch_is_rejected_before_sqlite_commit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app.guide.application import chat_api_adapter
    from app.guide_runtime.composition import (
        build_consultation_vertical_runtime,
        build_feedback_service,
    )
    from tests.guide.runtime.test_composition import StoredVectorEncoder

    state_root = tmp_path / "guide-state"
    image_bundles = build_image_bundle_service(
        database_path=state_root / "image_bundles.sqlite3"
    )
    consultation_runtime = build_consultation_vertical_runtime(
        state_dir=state_root,
    )
    image_orchestrator = build_image_recommendation_orchestrator(
        repo_root=REPO_ROOT,
        image_bundle_service=image_bundles,
        consultation_runtime=consultation_runtime,
        encoder=StoredVectorEncoder(53),
    )
    client = TestClient(
        create_app(
            consultation_runtime=consultation_runtime,
            image_bundle_service=image_bundles,
            image_runtime=StaticImageRuntime(image_orchestrator),
            feedback_service=build_feedback_service(
                state_directory=state_root
            ),
        )
    )
    session_id = "runtime-image-invalid-profile"
    receipt = _upload_bundle(client, session_id=session_id)
    original_adapter = chat_api_adapter._to_legacy_data

    def mismatch_product_profile(event):
        payload = original_adapter(event)
        if getattr(event, "event", None) == "products":
            payload = deepcopy(payload)
            payload["products"][0]["category_profile"] = "fragrance"
        return payload

    monkeypatch.setattr(
        chat_api_adapter,
        "_to_legacy_data",
        mismatch_product_profile,
    )

    response = client.post(
        "/api/v1/chat/stream",
        json={
            "message": "150元以内找相似款",
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
                    "error": "GUIDE_EVENT_CONTRACT_INVALID",
                    "message": "推荐响应不完整，请稍后重试。",
                },
            ),
        ],
        "durable_version": 0,
        "feedback_target_count": 0,
    }

    monkeypatch.setattr(
        chat_api_adapter,
        "_to_legacy_data",
        original_adapter,
    )
    accepted = _events(
        client.post(
            "/api/v1/chat/stream",
            json={
                "message": "150元以内找相似款",
                "session_id": session_id,
                "conversation_version": 0,
                "image_bundle_id": receipt["bundle_id"],
                "image_bundle_version": receipt["version"],
                "image_bundle_token": receipt["owner_token"],
            },
        )
    )
    stored = consultation_runtime.conversation_state.load(session_id)

    assert accepted[-2:] == [
        (
            "feedback_target",
            {
                "conversation_version": 1,
                "displayed_product_ids": [54],
                "profile_version": None,
            },
        ),
        ("end", {"conversation_version": 1}),
    ]
    assert stored is not None
    assert stored.version == 1
    assert feedback_target_count() == 1


def test_runtime_disconnect_before_end_delivery_does_not_commit() -> None:
    from app.guide.adapters.state import InMemoryConversationState
    from app.guide_runtime.composition import (
        compose_text_recommendation_orchestrator,
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
    canonical = REPO_ROOT / "data" / "canonical"
    real_reader = CanonicalProductReader.from_files(
        manifest_path=canonical / "core_products_v1_manifest.json",
        products_path=canonical / "core_products_v1.jsonl",
    )
    real_product_assets = load_seed_product_assets(
        manifest_path=canonical / "seed_product_images_v1_manifest.json",
        products_path=canonical / "seed_product_images_v1.jsonl",
        asset_root=REPO_ROOT,
    )
    orchestrator = compose_text_recommendation_orchestrator(
        real_reader,
        product_assets=real_product_assets,
        conversation_state=state,
    )
    app = create_app(
        orchestrator=orchestrator,
        feedback_service=feedback,
        image_runtime=StaticImageRuntime(object()),
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

    async def consume() -> list[str]:
        return [chunk async for chunk in response.body_iterator]

    chunks = asyncio.run(consume())

    assert "event: end" not in "".join(chunks)
    assert state.save_calls == 0
    assert state.load("runtime-public-event-delivery") is None
    assert feedback.completions == []


@pytest.mark.parametrize("owner", ["text", "image", "consultation"])
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
    owner,
    spec_version,
    outcome,
) -> None:
    from app.guide.adapters.state import InMemoryConversationState
    from app.guide_runtime.composition import (
        compose_text_recommendation_orchestrator,
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

    canonical = REPO_ROOT / "data" / "canonical"
    reader = CanonicalProductReader.from_files(
        manifest_path=canonical / "core_products_v1_manifest.json",
        products_path=canonical / "core_products_v1.jsonl",
    )
    assets = load_seed_product_assets(
        manifest_path=canonical / "seed_product_images_v1_manifest.json",
        products_path=canonical / "seed_product_images_v1.jsonl",
        asset_root=REPO_ROOT,
    )
    state = CountingConversationState()
    feedback = _PreparedRecordingFeedback()
    orchestrator = compose_text_recommendation_orchestrator(
        reader,
        product_assets=assets,
        conversation_state=state,
    )
    consultation_runtime = None
    payload_kwargs = {}
    if owner == "image":
        payload_kwargs = {
            "image_bundle_id": "bundle_" + "a" * 32,
            "image_bundle_version": 1,
            "image_bundle_token": "owner_" + "b" * 43,
        }
    elif owner == "consultation":
        class ConsultationOwner:
            _conversation_state = orchestrator._conversation_state

            def claims(self, turn):
                del turn
                return True

            def has_session(self, turn):
                del turn
                return False

            def stream(self, turn):
                yield from orchestrator.stream(turn)

        consultation_runtime = SimpleNamespace(
            consultation=ConsultationOwner(),
            recommendation=orchestrator,
        )
    app = create_app(
        orchestrator=orchestrator,
        consultation_runtime=consultation_runtime,
        feedback_service=feedback,
        image_runtime=StaticImageRuntime(orchestrator),
    )
    route = next(
        route
        for route in app.routes
        if getattr(route, "path", None) == "/api/v1/chat/stream"
    )
    session_id = f"runtime-{owner}-asgi-{spec_version}-{outcome}"
    payload = ChatStreamRequest(
        message="500 元内敏感肌修护精华",
        session_id=session_id,
        conversation_version=0,
        **payload_kwargs,
    )

    async def exercise() -> list[dict[str, Any]]:
        response = await route.endpoint(ConnectedRequest(), payload)

        def assert_uncommitted() -> None:
            assert state.save_calls == 0
            assert state.load(session_id) is None
            assert feedback.persisted == []

        def assert_committed() -> None:
            snapshot = state.load(session_id)
            assert state.save_calls == 1
            assert snapshot is not None
            assert snapshot.version == 1
            assert len(feedback.persisted) == 1

        return await _drive_asgi_terminal_delivery(
            response,
            spec_version=spec_version,
            outcome=outcome,
            assert_uncommitted=assert_uncommitted,
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


@pytest.mark.parametrize(
    ("owner", "has_feedback_target"),
    [
        ("image", True),
        ("consultation", True),
        ("text", True),
    ],
)
def test_runtime_terminal_feedback_and_end_share_one_delivery_chunk(
    owner,
    has_feedback_target,
) -> None:
    from app.guide.adapters.state import InMemoryConversationState
    from app.guide_runtime.composition import (
        compose_text_recommendation_orchestrator,
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

    canonical = REPO_ROOT / "data" / "canonical"
    reader = CanonicalProductReader.from_files(
        manifest_path=canonical / "core_products_v1_manifest.json",
        products_path=canonical / "core_products_v1.jsonl",
    )
    assets = load_seed_product_assets(
        manifest_path=canonical / "seed_product_images_v1_manifest.json",
        products_path=canonical / "seed_product_images_v1.jsonl",
        asset_root=REPO_ROOT,
    )
    state = CountingConversationState()
    feedback = RecordingFeedback()
    orchestrator = compose_text_recommendation_orchestrator(
        reader,
        product_assets=assets,
        conversation_state=state,
    )
    consultation_runtime = None
    payload_kwargs = {}
    if owner == "image":
        payload_kwargs = {
            "image_bundle_id": "bundle_" + "a" * 32,
            "image_bundle_version": 1,
            "image_bundle_token": "owner_" + "b" * 43,
        }
    elif owner == "consultation":
        class ConsultationOwner:
            _conversation_state = orchestrator._conversation_state

            def claims(self, turn):
                del turn
                return True

            def has_session(self, turn):
                del turn
                return False

            def stream(self, turn):
                yield from orchestrator.stream(turn)

        consultation_runtime = SimpleNamespace(
            consultation=ConsultationOwner(),
            recommendation=orchestrator,
        )
    app = create_app(
        orchestrator=orchestrator,
        consultation_runtime=consultation_runtime,
        feedback_service=feedback,
        image_runtime=StaticImageRuntime(orchestrator),
    )
    route = next(
        route
        for route in app.routes
        if getattr(route, "path", None) == "/api/v1/chat/stream"
    )
    session_id = f"runtime-{owner}-atomic-terminal"
    payload = ChatStreamRequest(
        message="500 元内敏感肌修护精华",
        session_id=session_id,
        conversation_version=0,
        **payload_kwargs,
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
        "terminal_names": (
            ["feedback_target", "end"]
            if has_feedback_target
            else ["end"]
        ),
        "saw_feedback_target": has_feedback_target,
        "saw_end": True,
        "state": 1,
        "state_commits": 1,
        "feedback": int(has_feedback_target),
    }


@pytest.mark.parametrize(
    "owner",
    ["image", "consultation", "text"],
)
@pytest.mark.parametrize("transport", ["stream", "message"])
def test_runtime_commit_failure_emits_one_error_without_feedback(
    owner,
    transport,
) -> None:
    from app.guide.adapters.state import InMemoryConversationState
    from app.guide_runtime.composition import (
        compose_text_recommendation_orchestrator,
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

    canonical = REPO_ROOT / "data" / "canonical"
    reader = CanonicalProductReader.from_files(
        manifest_path=canonical / "core_products_v1_manifest.json",
        products_path=canonical / "core_products_v1.jsonl",
    )
    assets = load_seed_product_assets(
        manifest_path=canonical / "seed_product_images_v1_manifest.json",
        products_path=canonical / "seed_product_images_v1.jsonl",
        asset_root=REPO_ROOT,
    )
    state = FailingConversationState()
    feedback = RecordingFeedback()
    orchestrator = compose_text_recommendation_orchestrator(
        reader,
        product_assets=assets,
        conversation_state=state,
    )
    consultation_runtime = None
    payload = {
        "message": "500 元内敏感肌修护精华",
        "session_id": f"runtime-{owner}-commit-failure",
        "conversation_version": 0,
    }
    if owner == "image":
        payload.update(
            {
                "image_bundle_id": "bundle_" + "a" * 32,
                "image_bundle_version": 1,
                "image_bundle_token": "owner_" + "b" * 43,
            }
        )
    elif owner == "consultation":
        class ConsultationOwner:
            _conversation_state = orchestrator._conversation_state

            def claims(self, turn):
                del turn
                return True

            def has_session(self, turn):
                del turn
                return False

            def stream(self, turn):
                yield from orchestrator.stream(turn)

        consultation_runtime = SimpleNamespace(
            consultation=ConsultationOwner(),
            recommendation=orchestrator,
        )
    response = TestClient(
        create_app(
            orchestrator=orchestrator,
            consultation_runtime=consultation_runtime,
            feedback_service=feedback,
            image_runtime=StaticImageRuntime(orchestrator),
        )
    ).post(
        f"/api/v1/chat/{transport}",
        json=payload,
    )
    events = (
        _events(response)
        if transport == "stream"
        else [("error", response.json()["detail"])]
    )
    names = [name for name, _ in events]

    assert state.save_calls == 1
    assert state.load(f"runtime-{owner}-commit-failure") is None
    if transport == "stream":
        assert names[-3:] == [
            "feedback_target",
            "end",
            "delivery_control",
        ]
        assert events[-1][1] == {
            "status": "conversation_commit_failed",
            "fatal": True,
        }
        assert len(feedback.completions) == 1
        assert feedback.persisted == []
    else:
        assert names == ["error"]
        assert feedback.completions == []
        assert feedback.persisted == []


@pytest.mark.parametrize("owner", ["image", "consultation", "text"])
def test_runtime_feedback_persist_failure_keeps_conversation_commit(
    owner,
) -> None:
    from app.guide.adapters.state import InMemoryConversationState
    from app.guide_runtime.composition import (
        compose_text_recommendation_orchestrator,
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

    canonical = REPO_ROOT / "data" / "canonical"
    reader = CanonicalProductReader.from_files(
        manifest_path=canonical / "core_products_v1_manifest.json",
        products_path=canonical / "core_products_v1.jsonl",
    )
    assets = load_seed_product_assets(
        manifest_path=canonical / "seed_product_images_v1_manifest.json",
        products_path=canonical / "seed_product_images_v1.jsonl",
        asset_root=REPO_ROOT,
    )
    state = CountingConversationState()
    feedback = FailingFeedback()
    orchestrator = compose_text_recommendation_orchestrator(
        reader,
        product_assets=assets,
        conversation_state=state,
    )
    consultation_runtime = None
    payload = {
        "message": "500 元内敏感肌修护精华",
        "session_id": f"runtime-{owner}-feedback-persist-failure",
        "conversation_version": 0,
    }
    if owner == "image":
        payload.update(
            {
                "image_bundle_id": "bundle_" + "a" * 32,
                "image_bundle_version": 1,
                "image_bundle_token": "owner_" + "b" * 43,
            }
        )
    elif owner == "consultation":
        class ConsultationOwner:
            _conversation_state = orchestrator._conversation_state

            def claims(self, turn):
                del turn
                return True

            def has_session(self, turn):
                del turn
                return False

            def stream(self, turn):
                yield from orchestrator.stream(turn)

        consultation_runtime = SimpleNamespace(
            consultation=ConsultationOwner(),
            recommendation=orchestrator,
        )
    response = TestClient(
        create_app(
            orchestrator=orchestrator,
            consultation_runtime=consultation_runtime,
            feedback_service=feedback,
            image_runtime=StaticImageRuntime(orchestrator),
        )
    ).post(
        "/api/v1/chat/stream",
        json=payload,
    )
    events = _events(response)
    names = [name for name, _ in events]
    snapshot = state.load(payload["session_id"])

    assert names[-3:] == [
        "feedback_target",
        "end",
        "delivery_control",
    ]
    assert events[-1][1] == {
        "status": "feedback_target_persist_failed",
        "fatal": False,
    }
    assert state.save_calls == 1
    assert snapshot is not None
    assert snapshot.version == 1
    assert len(feedback.persisted) == 1


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
            "image_results": [],
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

    vertical = build_consultation_vertical_runtime(
        state_dir=tmp_path / "consultation-state",
    )
    client = TestClient(
        create_app(
            consultation_runtime=vertical,
            image_runtime=StaticImageRuntime(object()),
        )
    )
    session_id = "runtime-consultation-profile"
    version = 0
    for message, typed_event in zip(
        (
            "我不知道自己是什么肤质",
            "会",
            "不会",
            "不会",
            "不会",
            "不会",
            "我确认是干皮",
        ),
        (
            "consultation_observation",
            "consultation_observation",
            "consultation_observation",
            "consultation_observation",
            "consultation_observation",
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
    assert stored.query_context is not None
    assert stored.query_context.skin == "dry"


def test_runtime_message_continues_active_stream_consultation(
    tmp_path: Path,
) -> None:
    from app.guide_runtime.composition import (
        build_consultation_vertical_runtime,
    )

    vertical = build_consultation_vertical_runtime(
        state_dir=tmp_path / "consultation-state",
    )
    client = TestClient(
        create_app(
            consultation_runtime=vertical,
            image_runtime=StaticImageRuntime(object()),
        )
    )
    session_id = "runtime-consultation-stream-message-parity"
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
    assert entered[-1] == (
        "end",
        {"conversation_version": 1},
    )

    response = client.post(
        "/api/v1/chat/message",
        json={
            "message": "会",
            "session_id": session_id,
            "conversation_version": 1,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["intent"]["intent"] == "consultation_answer"
    assert payload["consultation_observation"] is not None
    assert payload["card_display_contract"]["mode"] == "none"
    assert payload["products"] == []
    assert payload["conversation_version"] == 2


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
    state = (
        runtime_app.state.orchestrator
        ._conversation_state
        ._delegate
    )
    stored = state.load(session_id)
    assert stored is not None
    assert stored.pending_turn is not None

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


def test_runtime_text_non_stream_rejects_incomplete_guide_event_stream() -> None:
    client = TestClient(
        create_app(
            orchestrator=MissingEndImageOrchestrator(),
            image_runtime=StaticImageRuntime(object()),
        )
    )

    response = client.post(
        "/api/v1/chat/message",
        json={
            "message": "500 元内敏感肌修护精华",
            "session_id": "runtime-incomplete-text-events",
            "conversation_version": 0,
        },
    )

    assert response.status_code == 503
    assert response.json()["detail"] == {
        "code": "GUIDE_EVENT_CONTRACT_INVALID",
        "message": "推荐响应不完整，请稍后重试。",
    }


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
    ("followup", "expected_ids", "expected_version"),
    MULTITURN_CASES,
)
def test_runtime_http_supports_every_formal_multiturn_route(
    followup: str,
    expected_ids: list[int],
    expected_version: int,
) -> None:
    client = TestClient(create_app())
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
    assert [
        item["id"]
        for item in products["products"]
    ] == expected_ids
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
) -> None:
    client = TestClient(create_app())
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


def test_http_round_trips_budget_revision_context() -> None:
    client = TestClient(create_app())
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
    message = next(
        data for name, data in events if name == "message"
    )

    assert [item["id"] for item in products["products"]] == [91]
    assert decision["winner_status"] == "INSUFFICIENT_FOR_WINNER"
    assert "预算上限调整为 ¥100" in message["content"]
    assert events[-1] == (
        "end",
        {"conversation_version": 2},
    )


def test_http_client_cannot_override_server_query_context() -> None:
    client = TestClient(create_app())
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
    products = next(
        data
        for name, data in _events(response)
        if name == "products"
    )

    assert [item["id"] for item in products["products"]] == [91]


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
    message = next(data for name, data in events if name == "message")

    assert message["content"] == (
        "我还没有前面那组商品，请先发起一次推荐。"
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
    events = _events(response)

    assert events == [
        ("start", {"session_id": "image-test"}),
        (
            "error",
            {
                "error": "IMAGE_BUNDLE_UNAVAILABLE",
                "message": "图片引用不可用，请重新上传。",
            },
        ),
    ]


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
    message = next(data for name, data in events if name == "message")
    assert message["content"].strip()


def test_public_error_is_terminal_and_hides_internal_detail() -> None:
    class PublicErrorOrchestrator:
        def stream(self, turn):
            yield StartEvent(
                data=StartData(session_id=turn.session_id)
            )
            yield ErrorEvent(
                data=ErrorData(
                    code="GUIDE_INTERNAL_ERROR",
                    message="推荐暂时不可用，请稍后重试。",
                )
            )

    client = TestClient(
        create_app(orchestrator=PublicErrorOrchestrator())
    )
    response = client.post(
        "/api/v1/chat/stream",
        json={
            "message": "500 内适合油敏肌的防晒",
            "session_id": "error-test",
            "stream": True,
        },
    )
    events = _events(response)

    assert [name for name, _ in events] == ["start", "error"]
    assert "end" not in [name for name, _ in events]
    assert events[-1][1] == {
        "error": "GUIDE_INTERNAL_ERROR",
        "message": "推荐暂时不可用，请稍后重试。",
    }


def test_app_reuses_the_injected_orchestrator() -> None:
    sentinel = object()

    app = create_app(orchestrator=sentinel)

    assert app.state.orchestrator is sentinel


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
            "message": "看看这两张图",
            "session_id": session_id,
            "conversation_version": 0,
            "image_bundle_id": receipt["bundle_id"],
            "image_bundle_version": receipt["version"],
            "image_bundle_token": receipt["owner_token"],
            "image_results": [
                {
                    "product_id": 999,
                    "winner": True,
                    "confidence": 1.0,
                }
            ],
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
    assert decision["comparison_data"]["status"] == "winner"
    assert decision["comparison_data"]["winner_reference"]["ordinal"] == 2
    assert contract == {
        "mode": "comparison",
        "visible_product_ids": [53, 55],
        "max_cards": 2,
        "reason": "comparison",
    }
    assert [product["id"] for product in products] == [53, 55]
    assert presentation["mode"] == "comparison"
    assert presentation["winner"]["status"] == "selected"
    assert presentation["winner"]["winner_product_id"] == 55
    assert presentation["winner"]["fact_ids"]
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
    assert "999" not in response.text


def test_runtime_non_stream_two_image_matches_sse_contract() -> None:
    client = _image_client(product_ids=(53, 55))
    session_id = "runtime-two-image-message"
    receipt = _upload_bundle(client, session_id=session_id, count=2)

    response = client.post(
        "/api/v1/chat/message",
        json={
            "message": "比较这两张图",
            "session_id": session_id,
            "conversation_version": 7,
            "image_bundle_id": receipt["bundle_id"],
            "image_bundle_version": receipt["version"],
            "image_bundle_token": receipt["owner_token"],
            "image_results": [{"product_id": 999, "winner": True}],
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["intent"]["intent"] == "image_compare"
    assert payload["comparison_data"]["status"] == "winner"
    assert payload["comparison_data"]["winner_reference"]["ordinal"] == 2
    assert payload["decision_process"]["steps"][0]["data"][
        "outcome"
    ] == payload["comparison_data"]
    assert payload["answer_contract"]["product_count"] == 2
    assert payload["card_display_contract"] == {
        "mode": "comparison",
        "visible_product_ids": [53, 55],
        "max_cards": 2,
        "reason": "comparison",
    }
    assert [item["id"] for item in payload["products"]] == [53, 55]
    assert [
        item["confirmed_product_id"]
        for item in payload["metadata"]["image_observations"]
    ] == [53, 55]
    assert payload["conversation_version"] == 8
    assert payload["metadata"]["conversation_version"] == 8
    assert payload["feedback_target"]["conversation_version"] == 8
    assert payload["session_id"] == session_id
    assert "未评估肤质或功效优劣" in payload["response"]
    assert "999" not in response.text
    assert receipt["owner_token"] not in response.text


def test_runtime_non_stream_rejects_incomplete_guide_event_stream() -> None:
    service = ImageBundleService(
        state=InMemoryImageBundleState(max_bundles=4)
    )
    client = TestClient(
        create_app(
            image_bundle_service=service,
            image_runtime=StaticImageRuntime(
                MissingEndImageOrchestrator()
            ),
        )
    )
    receipt = _upload_bundle(
        client,
        session_id="runtime-incomplete-events",
    )

    response = client.post(
        "/api/v1/chat/message",
        json={
            "message": "看看图片",
            "session_id": "runtime-incomplete-events",
            "image_bundle_id": receipt["bundle_id"],
            "image_bundle_version": receipt["version"],
            "image_bundle_token": receipt["owner_token"],
        },
    )

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == (
        "GUIDE_EVENT_CONTRACT_INVALID"
    )


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
    assert _events(injected) == [
        ("start", {"session_id": "runtime-injected-image"}),
        (
            "error",
            {
                "error": "IMAGE_BUNDLE_UNAVAILABLE",
                "message": "图片引用不可用，请重新上传。",
            },
        ),
    ]


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
    first = TestClient(
        create_app(
            image_bundle_service=first_service,
            image_runtime=_static_image_runtime(first_service),
        )
    )
    second = TestClient(
        create_app(
            image_bundle_service=second_service,
            image_runtime=_static_image_runtime(second_service),
        )
    )
    session_id = "shared-image-bundle"
    receipt = _upload_bundle(first, session_id=session_id)

    response = second.post(
        "/api/v1/chat/stream",
        json={
            "message": "看看图片",
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
        args=(state_directory, receipt, queue),
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
        args=(state_directory, receipt, replay_queue),
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
        TestClient(create_app(orchestrator=object())),
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
        TestClient(create_app(orchestrator=object())),
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
