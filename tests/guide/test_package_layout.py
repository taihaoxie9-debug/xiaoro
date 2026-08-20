from __future__ import annotations

import importlib
from pathlib import Path


GUIDE_ROOT = Path(__file__).resolve().parents[2] / "app" / "guide"

FORMAL_PACKAGES = (
    "understanding",
    "intent",
    "retrieval",
    "decision",
    "presentation",
    "feedback",
    "application",
    "adapters",
    "adapters.llm",
    "adapters.catalog",
    "adapters.state",
)

STALE_PACKAGES = (
    "catalog",
    "response",
    "orchestration",
)


def test_formal_guide_packages_are_importable() -> None:
    for package in FORMAL_PACKAGES:
        module = importlib.import_module(f"app.guide.{package}")

        assert module.__file__ is not None
        assert Path(module.__file__).name == "__init__.py"


def test_stale_guide_packages_do_not_exist() -> None:
    for package in STALE_PACKAGES:
        assert not (GUIDE_ROOT / package).exists()
