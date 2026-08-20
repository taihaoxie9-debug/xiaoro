from __future__ import annotations

import ast
from dataclasses import is_dataclass
from pathlib import Path
from textwrap import dedent

import pytest

from app.guide import check_boundaries as boundary_checker


def write_source(root: Path, relative_path: str, source: str) -> Path:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dedent(source).lstrip(), encoding="utf-8")
    return path


def run_checker(root: Path) -> list[object]:
    check_boundaries = getattr(boundary_checker, "check_boundaries", None)
    if check_boundaries is not None:
        return check_boundaries(root)

    # Compatibility path used only to prove that the legacy checker misses
    # violations in an explicitly supplied temporary root.
    violations: list[object] = []
    for path in sorted(root.rglob("*.py")):
        boundary_checker.check_file(path, violations)
    return violations


def assert_single_violation(
    root: Path,
    expected_rule: str,
    *,
    expected_file: str,
    expected_line: int,
) -> None:
    violations = run_checker(root)

    assert len(violations) == 1
    violation = violations[0]
    assert is_dataclass(violation)
    assert violation.rule == expected_rule
    assert violation.file == expected_file
    assert violation.line == expected_line
    assert violation.detail


def test_legal_public_contract_imports_and_nonsemantic_text_pass(
    tmp_path: Path,
) -> None:
    root = tmp_path / "app" / "guide"
    write_source(
        root,
        "presentation/view.py",
        """
        from app.guide.decision.contracts import DecisionResult
        from app.guide.retrieval.contracts import RetrievalResult

        NOTE = "app.services raw_description winner semantic_lexicon"
        # from app.guide.adapters.catalog.reader import CanonicalProductReader
        """,
    )
    write_source(
        root,
        "application/orchestrator.py",
        """
        from app.guide.application.contracts import UserTurn
        from app.guide.presentation.contracts import ResponsePlan

        class GuideOrchestrator:
            pass
        """,
    )

    assert run_checker(root) == []


@pytest.mark.parametrize(
    ("statement", "expected_line"),
    [
        ("import app.services", 1),
        ("from app.services.v2 import agent", 1),
        ("from ... import services", 1),
    ],
)
def test_runtime_cannot_import_legacy_services(
    tmp_path: Path,
    statement: str,
    expected_line: int,
) -> None:
    root = tmp_path / "app" / "guide"
    write_source(root, "intent/legacy.py", statement)

    assert_single_violation(
        root,
        "FORBIDDEN_RUNTIME_IMPORT",
        expected_file="intent/legacy.py",
        expected_line=expected_line,
    )


def test_runtime_cannot_import_sealed_evidence_tooling(tmp_path: Path) -> None:
    root = tmp_path / "app" / "guide"
    write_source(
        root,
        "feedback/audit.py",
        """
        from tools.evidence_audit import ledger
        """,
    )

    assert_single_violation(
        root,
        "SEALED_TOOLING_IMPORT",
        expected_file="feedback/audit.py",
        expected_line=1,
    )


@pytest.mark.parametrize(
    ("statement", "expected_rule"),
    [
        (
            'import_module("app.services.v2.presenter")',
            "FORBIDDEN_RUNTIME_IMPORT",
        ),
        (
            '__import__("app.services")',
            "FORBIDDEN_RUNTIME_IMPORT",
        ),
        (
            'importlib.import_module("tools.evidence_audit.ledger")',
            "SEALED_TOOLING_IMPORT",
        ),
    ],
)
def test_runtime_cannot_dynamically_import_forbidden_modules(
    tmp_path: Path,
    statement: str,
    expected_rule: str,
) -> None:
    root = tmp_path / "app" / "guide"
    write_source(root, "intent/dynamic.py", statement)

    assert_single_violation(
        root,
        expected_rule,
        expected_file="intent/dynamic.py",
        expected_line=1,
    )


@pytest.mark.parametrize(
    "statement",
    [
        (
            "from app.guide.adapters.catalog.canonical_product_reader "
            "import CanonicalProductReader"
        ),
        (
            "from ..adapters.catalog.canonical_product_reader "
            "import CanonicalProductReader"
        ),
    ],
)
def test_presentation_cannot_import_concrete_retrieval_adapter(
    tmp_path: Path,
    statement: str,
) -> None:
    root = tmp_path / "app" / "guide"
    write_source(root, "presentation/product_cards.py", statement)

    assert_single_violation(
        root,
        "PRESENTATION_ADAPTER_IMPORT",
        expected_file="presentation/product_cards.py",
        expected_line=1,
    )


@pytest.mark.parametrize(
    ("parameter", "expression"),
    [
        ("candidate", "candidate.raw_description"),
        ("candidate", "candidate.reviews"),
        ("candidate", "candidate.ocr_text"),
        ("ocr_text", "ocr_text"),
    ],
)
def test_decision_cannot_read_raw_content(
    tmp_path: Path,
    parameter: str,
    expression: str,
) -> None:
    root = tmp_path / "app" / "guide"
    write_source(
        root,
        "decision/ranker.py",
        f"""
        def decide({parameter}):
            return {expression}
        """,
    )

    assert_single_violation(
        root,
        "DECISION_RAW_FIELD_ACCESS",
        expected_file="decision/ranker.py",
        expected_line=2,
    )


def test_retrieval_cannot_select_a_winner(tmp_path: Path) -> None:
    root = tmp_path / "app" / "guide"
    write_source(
        root,
        "retrieval/search.py",
        """
        def select_winner(candidates):
            return candidates[0]
        """,
    )

    assert_single_violation(
        root,
        "RETRIEVAL_WINNER_LOGIC",
        expected_file="retrieval/search.py",
        expected_line=1,
    )


def test_orchestrator_cannot_define_scoring_logic(tmp_path: Path) -> None:
    root = tmp_path / "app" / "guide"
    write_source(
        root,
        "application/orchestrator.py",
        """
        def score_candidates(candidates):
            return sorted(candidates)
        """,
    )

    assert_single_violation(
        root,
        "ORCHESTRATOR_SCORING_LOGIC",
        expected_file="application/orchestrator.py",
        expected_line=1,
    )


def test_real_text_orchestrator_cannot_define_scoring_logic(
    tmp_path: Path,
) -> None:
    root = tmp_path / "app" / "guide"
    write_source(
        root,
        "application/text_recommendation_flow.py",
        """
        def score_candidates(candidates):
            return candidates
        """,
    )

    assert_single_violation(
        root,
        "ORCHESTRATOR_SCORING_LOGIC",
        expected_file="application/text_recommendation_flow.py",
        expected_line=1,
    )


def test_application_adapter_cannot_define_fake_scores(
    tmp_path: Path,
) -> None:
    root = tmp_path / "app" / "guide"
    write_source(
        root,
        "application/chat_api_adapter.py",
        """
        def _match_score(value):
            return 0.9
        """,
    )

    assert_single_violation(
        root,
        "ORCHESTRATOR_SCORING_LOGIC",
        expected_file="application/chat_api_adapter.py",
        expected_line=1,
    )


def test_runtime_rejects_nonliteral_dynamic_import(
    tmp_path: Path,
) -> None:
    root = tmp_path / "app" / "guide"
    write_source(
        root,
        "intent/dynamic.py",
        """
        from importlib import import_module
        module_name = "app.services.v2.agent"
        import_module(module_name)
        """,
    )

    assert_single_violation(
        root,
        "DYNAMIC_IMPORT_NOT_ALLOWED",
        expected_file="intent/dynamic.py",
        expected_line=3,
    )


def test_orchestrator_cannot_define_semantic_lexicon(tmp_path: Path) -> None:
    root = tmp_path / "app" / "guide"
    write_source(
        root,
        "application/orchestrator.py",
        """
        SEMANTIC_LEXICON = {"compare": ("versus", "better")}
        """,
    )

    assert_single_violation(
        root,
        "ORCHESTRATOR_SEMANTIC_LEXICON",
        expected_file="application/orchestrator.py",
        expected_line=1,
    )


def test_application_does_not_import_concrete_adapters() -> None:
    source = Path(
        "app/guide/application/text_recommendation_flow.py"
    ).read_text(encoding="utf-8")

    assert "app.guide.adapters" not in source


def test_production_defines_or_imports_no_retired_consultation_authority(
) -> None:
    retired_names = {
        "ConsultationSnapshot",
        "ConsultationStateConflict",
        "ConsultationStatePort",
        "InMemoryConsultationState",
    }
    retired_module = (
        "app.guide.adapters.state.in_memory_consultation_state"
    )
    violations: list[str] = []

    for root in (Path("app/guide"), Path("app/guide_runtime")):
        for path in sorted(root.rglob("*.py")):
            tree = ast.parse(
                path.read_text(encoding="utf-8"),
                filename=str(path),
            )
            for node in ast.walk(tree):
                if (
                    isinstance(node, (ast.ClassDef, ast.FunctionDef))
                    and node.name in retired_names
                ):
                    violations.append(
                        f"{path}:{node.lineno}:defines {node.name}"
                    )
                elif isinstance(node, ast.ImportFrom):
                    imported_names = {
                        alias.name for alias in node.names
                    }
                    for name in sorted(imported_names & retired_names):
                        violations.append(
                            f"{path}:{node.lineno}:imports {name}"
                        )
                    if node.module == retired_module:
                        violations.append(
                            f"{path}:{node.lineno}:imports {retired_module}"
                        )
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name == retired_module:
                            violations.append(
                                f"{path}:{node.lineno}:imports "
                                f"{retired_module}"
                            )

    assert violations == []
