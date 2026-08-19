from __future__ import annotations

import json
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.guide.adapters.state.in_memory_image_bundle_state import (
    InMemoryImageBundleState,
)
from app.guide.application.image_bundle_service import ImageBundleService
from app.guide.feedback.profile_contracts import ProfileOwnerRef
from app.guide_runtime.app import create_app
from app.guide_runtime.composition import (
    build_runtime_orchestrator,
    guide_image_runtime_lock,
)
from app.guide_runtime.image_runtime import ImageRuntimeHealth
from tests.guide.semantic_test_port import ExactEchoSemanticPort


class InactiveConsultation:
    def claims(self, turn) -> bool:
        del turn
        return False

    def has_session(self, turn) -> bool:
        del turn
        return False


class StaticImageRuntime:
    def __init__(self) -> None:
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
        raise AssertionError("image runtime should not be used")


class DisabledFeedback:
    def register_completed(self, **kwargs):
        del kwargs
        return None


def test_message_response_includes_replayable_presentation_contract(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("GUIDE_UNIFIED_ROUTER_ENABLED", "false")
    monkeypatch.delenv("GUIDE_COPY_LLM_API_KEY", raising=False)
    monkeypatch.delenv("GUIDE_COPY_LLM_MODEL", raising=False)
    orchestrator = build_runtime_orchestrator(
        state_dir=tmp_path / "state",
        semantic_intent=ExactEchoSemanticPort(),
    )
    image_bundles = ImageBundleService(
        state=InMemoryImageBundleState(max_bundles=4)
    )
    consultation = SimpleNamespace(
        consultation=InactiveConsultation(),
        recommendation=orchestrator,
        profile_owner=lambda session_id: ProfileOwnerRef(
            scope="anonymous_browser",
            subject_id=f"profile_{session_id}_0123456789",
        ),
    )
    app = create_app(
        orchestrator=orchestrator,
        consultation_runtime=consultation,
        image_bundle_service=image_bundles,
        image_runtime=StaticImageRuntime(),
        feedback_service=DisabledFeedback(),
    )

    response = TestClient(app).post(
        "/api/v1/chat/message",
        json={
            "message": "500 内适合油敏肌的防晒",
            "session_id": "presentation-http",
            "conversation_version": 0,
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    presentation = body["presentation_contract"]
    assert presentation["mode"] == "recommendation"
    assert presentation["copy_source"] == "fallback"
    assert presentation["card_display"][
        "visible_product_ids"
    ] == [101, 26, 52]
    restored = json.loads(
        json.dumps(
            presentation,
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    assert restored == presentation
    assert [
        section["product_id"]
        for section in restored["sections"]
        if section["kind"] == "product"
    ] == [101, 26, 52]
