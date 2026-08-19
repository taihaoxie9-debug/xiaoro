from __future__ import annotations

from app.guide_runtime.app import create_app
from app.guide_runtime.composition import build_runtime_orchestrator
from tests.guide.semantic_test_port import ExactEchoSemanticPort


app = create_app(
    orchestrator=build_runtime_orchestrator(
        semantic_intent=ExactEchoSemanticPort(),
    )
)
