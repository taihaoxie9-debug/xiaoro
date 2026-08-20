from __future__ import annotations

import ast
import importlib
import inspect
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Protocol, get_type_hints

from app.guide.application.contracts import UserTurn
from app.guide.presentation.contracts import ResponsePlan
from app.guide.presentation.sse_events import SseEvent


REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_NAME = "app.guide.application.orchestrator"


def load_orchestrator_module() -> object:
    return importlib.import_module(MODULE_NAME)


def test_guide_orchestrator_protocol_maps_user_turn_to_response_plan() -> None:
    module = load_orchestrator_module()
    guide_orchestrator = module.GuideOrchestrator

    assert issubclass(guide_orchestrator, Protocol)

    signature = inspect.signature(guide_orchestrator.orchestrate)
    assert list(signature.parameters) == ["self", "turn"]
    assert get_type_hints(guide_orchestrator.orchestrate) == {
        "turn": UserTurn,
        "return": ResponsePlan,
    }

    stream_signature = inspect.signature(guide_orchestrator.stream)
    assert list(stream_signature.parameters) == ["self", "turn"]
    assert get_type_hints(
        guide_orchestrator.stream,
        include_extras=True,
    ) == {
        "turn": UserTurn,
        "return": Iterator[SseEvent],
    }


def test_orchestrator_module_contains_only_imports_and_a_protocol_signature() -> None:
    module = load_orchestrator_module()
    tree = ast.parse(inspect.getsource(module))

    assert all(isinstance(node, (ast.ImportFrom, ast.ClassDef)) for node in tree.body)

    class_nodes = [node for node in tree.body if isinstance(node, ast.ClassDef)]
    assert len(class_nodes) == 1

    method_nodes = [
        node for node in class_nodes[0].body if isinstance(node, ast.FunctionDef)
    ]
    assert len(method_nodes) == 2
    for method_node in method_nodes:
        assert len(method_node.body) == 1
        assert isinstance(method_node.body[0], ast.Expr)
        assert isinstance(method_node.body[0].value, ast.Constant)
        assert method_node.body[0].value.value is Ellipsis


def test_importing_orchestrator_does_not_load_runtime_integrations() -> None:
    script = f"""
import sys

before = set(sys.modules)
import {MODULE_NAME}
loaded = set(sys.modules) - before
forbidden = ("app.services", "redis", "pymilvus", "psycopg", "openai")
unexpected = sorted(
    name
    for name in loaded
    if any(name == prefix or name.startswith(prefix + ".") for prefix in forbidden)
)
if unexpected:
    raise RuntimeError(unexpected)
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout == ""
    assert completed.stderr == ""
