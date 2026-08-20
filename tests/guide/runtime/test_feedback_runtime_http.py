import asyncio
import json
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from app.guide.feedback.delivery import FeedbackTargetReceipt
from app.guide.presentation.sse_events import ErrorData, ErrorEvent
from app.guide_runtime.app import create_app
from app.guide_runtime.composition import (
    build_consultation_vertical_runtime as _build_consultation_vertical_runtime,
    build_runtime_orchestrator as _build_runtime_orchestrator,
)
from tests.guide.runtime.test_runtime_http import (
    StaticImageRuntime,
    _events,
)
from tests.guide.semantic_test_port import ExactEchoSemanticPort


def build_runtime_orchestrator(*args, **kwargs):
    kwargs.setdefault("semantic_intent", ExactEchoSemanticPort())
    return _build_runtime_orchestrator(*args, **kwargs)


def build_consultation_vertical_runtime(*args, **kwargs):
    kwargs.setdefault("semantic_intent", ExactEchoSemanticPort())
    return _build_consultation_vertical_runtime(*args, **kwargs)


@pytest.fixture(autouse=True)
def _inject_semantic_runtime(
    monkeypatch,
) -> None:
    from app.guide_runtime import app as app_module

    monkeypatch.setattr(
        app_module,
        "build_runtime_orchestrator",
        build_runtime_orchestrator,
    )
    monkeypatch.setattr(
        app_module,
        "build_consultation_vertical_runtime",
        build_consultation_vertical_runtime,
    )


def test_runtime_publishes_feedback_capability_and_http_vertical(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("XIAORO_GUIDE_STATE_DIR", str(tmp_path))
    client = TestClient(
        create_app(image_runtime=StaticImageRuntime(object()))
    )

    page = client.get("/chat")
    assert page.status_code == 200
    assert "xiaoro_feedback_session=" in page.headers["set-cookie"]
    assert "HttpOnly" in page.headers["set-cookie"]

    health = client.get("/health")
    assert "trusted_feedback" in health.json()["capabilities"]

    session_id = "runtime-feedback-session"
    stream = client.post(
        "/api/v1/chat/stream",
        json={
            "message": "500 元内敏感肌修护精华",
            "session_id": session_id,
            "conversation_version": 0,
        },
    )
    events = _events(stream)
    names = [name for name, _ in events]
    receipt = next(
        data for name, data in events if name == "feedback_target"
    )

    assert names.index("feedback_target") < names.index("end")
    assert receipt["displayed_product_ids"] == [38, 91]
    assert "owner" not in json.dumps(receipt)
    assert "session_id" not in json.dumps(receipt)

    payload = {
        "conversation_version": receipt["conversation_version"],
        "profile_version": receipt["profile_version"],
        "idempotency_key": "runtime-feedback-idempotency-0001",
        "payload": {
            "event_type": "click",
            "product_id": 91,
        },
    }
    first = client.post(
        f"/api/v1/chat/sessions/{session_id}/feedback",
        json=payload,
    )
    replay = client.post(
        f"/api/v1/chat/sessions/{session_id}/feedback",
        json=payload,
    )

    assert first.status_code == 200, first.text
    assert replay.json() == first.json()
    assert first.json()["event_type"] == "click"


class _SlowFeedback:
    def __init__(self) -> None:
        self.finished_at = None

    def prepare_completed(self, *, actor, completion):
        assert actor.authorized_session_id == "runtime-feedback-threadpool"
        assert completion is not None
        return SimpleNamespace(
            receipt=FeedbackTargetReceipt(
                conversation_version=completion.conversation_version,
                displayed_product_ids=(91, 38),
                profile_version=None,
            )
        )

    def persist_prepared(self, prepared):
        time.sleep(0.2)
        self.finished_at = time.monotonic()
        return prepared.receipt

    def register_completed(self, *, actor, completion):
        prepared = self.prepare_completed(
            actor=actor,
            completion=completion,
        )
        return self.persist_prepared(prepared)

    def record(self, submission, *, actor):
        raise AssertionError("record is not used")


async def _exercise_feedback_threadpool() -> None:
    feedback = _SlowFeedback()
    app = create_app(
        feedback_service=feedback,
        image_runtime=StaticImageRuntime(object()),
    )
    heartbeat_at = None

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://runtime.test",
    ) as client:
        async def heartbeat() -> None:
            nonlocal heartbeat_at
            await asyncio.sleep(0.05)
            heartbeat_at = time.monotonic()

        response, _ = await asyncio.gather(
            client.post(
                "/api/v1/chat/stream",
                json={
                    "message": "500 元内敏感肌修护精华",
                    "session_id": "runtime-feedback-threadpool",
                    "conversation_version": 0,
                },
            ),
            heartbeat(),
        )

    assert response.status_code == 200
    assert feedback.finished_at is not None
    assert heartbeat_at is not None
    assert heartbeat_at < feedback.finished_at


def test_runtime_feedback_sqlite_boundary_stays_off_event_loop(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("XIAORO_GUIDE_STATE_DIR", str(tmp_path))
    asyncio.run(_exercise_feedback_threadpool())


def _confirm_dry_profile(
    client: TestClient,
    *,
    session_id: str,
) -> None:
    version = 0
    for message in (
        "我不知道自己是什么肤质",
        "会",
        "不会",
        "不会",
        "不会",
        "不会",
        "我确认是干皮",
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
        version = events[-1][1]["conversation_version"]


def test_runtime_new_sessions_do_not_inherit_server_actor_profile(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("XIAORO_GUIDE_STATE_DIR", str(tmp_path))
    vertical = build_consultation_vertical_runtime(
        state_dir=tmp_path,
    )
    client = TestClient(
        create_app(
            consultation_runtime=vertical,
            image_runtime=StaticImageRuntime(object()),
        )
    )
    client.get("/chat")
    _confirm_dry_profile(
        client,
        session_id="runtime-feedback-actor-consultation",
    )

    stream_events = _events(
        client.post(
            "/api/v1/chat/stream",
            json={
                "message": "500元内防晒",
                "session_id": "runtime-feedback-actor-stream",
                "conversation_version": 0,
            },
        )
    )
    stream_target = next(
        data
        for name, data in stream_events
        if name == "feedback_target"
    )
    message = client.post(
        "/api/v1/chat/message",
        json={
            "message": "500元内防晒",
            "session_id": "runtime-feedback-actor-message",
            "conversation_version": 0,
        },
    )

    assert stream_target["profile_version"] is None
    assert message.status_code == 200, message.text
    assert (
        message.json()["feedback_target"]["profile_version"]
        is None
    )


class _EndThenErrorOrchestrator:
    def __init__(self, delegate) -> None:
        self.delegate = delegate

    def stream(self, turn):
        yield from self.delegate.stream(turn)
        yield ErrorEvent(
            data=ErrorData(
                code="GUIDE_INTERNAL_ERROR",
                message="推荐暂时不可用，请稍后重试。",
            )
        )


def test_runtime_stream_does_not_publish_target_before_terminal_is_final(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("XIAORO_GUIDE_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("GUIDE_UNIFIED_ROUTER_ENABLED", "false")
    app = create_app(
        orchestrator=_EndThenErrorOrchestrator(
            build_runtime_orchestrator()
        ),
        image_runtime=StaticImageRuntime(object()),
    )
    events = _events(
        TestClient(app).post(
            "/api/v1/chat/stream",
            json={
                "message": "500元内防晒",
                "session_id": "runtime-feedback-end-then-error",
                "conversation_version": 0,
            },
        )
    )
    names = [name for name, _ in events]

    assert names[-1] == "error"
    assert "feedback_target" not in names
    assert "end" not in names
