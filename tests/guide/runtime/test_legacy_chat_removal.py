from __future__ import annotations

import ast
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]


def test_app_main_is_guide_compatibility_export() -> None:
    from app.guide_runtime.app import app as guide_app
    from app.guide_runtime.app import create_app as guide_create_app
    from app.main import app as compatibility_app
    from app.main import create_app as compatibility_create_app

    source = (REPO_ROOT / "app/main.py").read_text(encoding="utf-8")

    assert compatibility_app is guide_app
    assert compatibility_create_app is guide_create_app
    assert "app.database" not in source
    assert "app.services" not in source
    assert "include_router" not in source


def test_api_v1_package_does_not_eagerly_import_chat() -> None:
    source = (REPO_ROOT / "app/api/v1/__init__.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)
    eager_names = {
        alias.name
        for node in tree.body
        if isinstance(node, ast.ImportFrom) and node.module == "app.api.v1"
        for alias in node.names
    }
    exported_names = {
        element.value
        for node in tree.body
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name) and target.id == "__all__"
        if isinstance(node.value, ast.List)
        for element in node.value.elts
        if isinstance(element, ast.Constant)
        and isinstance(element.value, str)
    }

    assert "chat" not in eager_names
    assert "chat" not in exported_names
    assert {"upload", "search", "image_search", "rag", "decision", "documents"} <= (
        eager_names
    )


def test_services_package_has_no_eager_imports() -> None:
    source = (REPO_ROOT / "app/services/__init__.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)

    docstring = ast.get_docstring(tree)
    assert docstring is not None
    assert docstring.startswith("Non-chat service package.")
    assert "public runtime is owned by app.guide_runtime" in docstring
    assert not any(
        isinstance(node, (ast.Import, ast.ImportFrom))
        for node in tree.body
    )


def test_config_has_no_legacy_chat_or_v2_switches() -> None:
    source = (REPO_ROOT / "app/config.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    settings_class = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "Settings"
    )
    attributes = {
        node.target.id
        for node in settings_class.body
        if isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
    }
    forbidden = {
        "USE_V2_AGENT",
        "INTENT_LLM_ENABLED",
        "INTENT_LLM_CONFIDENCE_THRESHOLD",
        "V2_DISABLE_LLM",
        "V2_STATE_MACHINE_ENABLED",
        "V2_FOLLOWUP_LLM_JUDGE_ENABLED",
        "V2_FOLLOWUP_LLM_JUDGE_SHADOW_ENABLED",
        "V2_FOLLOWUP_LLM_JUDGE_MODEL",
        "V2_FOLLOWUP_LLM_JUDGE_MAX_TOKENS",
        "V2_FOLLOWUP_LLM_JUDGE_PROVIDER",
    }

    assert attributes.isdisjoint(forbidden)


def test_worker_keeps_non_chat_tasks_without_legacy_recommendation() -> None:
    source = (REPO_ROOT / "app/tasks/worker.py").read_text(encoding="utf-8")
    product_tasks_module = ".".join(("app", "tasks", "product", "tasks"))
    recommend_task = ".".join(("tasks", "product", "recommend"))

    assert product_tasks_module not in source
    assert recommend_task not in source
    assert "ShoppingAgent" not in source
    assert "def recommend_products" not in source
    assert "tasks.product.compare_prices" in source
    assert "app.tasks.evaluation.tasks" in source
    assert "app.tasks.rag.tasks" in source
    assert "app.tasks.image_tasks" in source
    assert not (REPO_ROOT / "app/tasks/product/tasks.py").exists()


def test_frontend_keeps_image_decisions_on_guide_backend() -> None:
    html = (REPO_ROOT / "app/static/chat.html").read_text(encoding="utf-8")
    retired_local_decisions = {
        "resolveImageTurnPolicy",
        "buildLocalImageIdentificationReply",
        "buildLocalImagePriceReply",
        "buildLocalImageJudgementReply",
        "composeImagePrompt",
    }

    assert all(name not in html for name in retired_local_decisions)
    assert "image_results" in html


def test_old_only_tests_and_scripts_are_removed() -> None:
    old_only_paths = (
        "tests/guide/application/test_chat_route_wiring.py",
        "tests/guide/application/test_feedback_http_vertical.py",
        "tests/guide/application/test_formal_chat_router_http.py",
        "tests/test_intent_integration.py",
        "tests/test_unified_chat_contract.py",
        "tests/test_v2_image_and_frontend_regressions.py",
        "tests/test_v2_state_machine.py",
        "scripts/batch_backend_test.py",
        "scripts/e2e_regression_test.py",
        "scripts/intent_baseline_probe.py",
        "scripts/layered_test_30.py",
        "scripts/llm_e2e_test.py",
        "scripts/llm50_quality_test.py",
        "scripts/llm50_v2_test.py",
        "scripts/nollm_e2e_test.py",
        "scripts/quick_5tests.py",
        "scripts/quick_regression.py",
        "scripts/smoke_llm.py",
        "scripts/test_v2_20cases.py",
        "scripts/test_v2_golden_cases.py",
        "scripts/test_v2_semantic_matrix.py",
    )

    assert [
        path
        for path in old_only_paths
        if (REPO_ROOT / path).exists()
    ] == []


def test_legacy_chat_source_tree_is_physically_removed() -> None:
    retired_paths = (
        "app/api/v1/chat.py",
        "app/services/agent.py",
        "app/services/intent.py",
        "app/services/conversation.py",
        "app/services/v2",
    )

    assert [
        path
        for path in retired_paths
        if (REPO_ROOT / path).exists()
    ] == []


def test_legacy_intent_prompts_are_removed_without_package_exports() -> None:
    retired_paths = (
        "app/prompts/intent_prompts.py",
        "app/prompts/test_intent_classifier.py",
    )
    source = (REPO_ROOT / "app/prompts/__init__.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)

    assert [
        path
        for path in retired_paths
        if (REPO_ROOT / path).exists()
    ] == []
    assert not any(
        isinstance(node, (ast.Import, ast.ImportFrom, ast.Assign))
        for node in tree.body
    )
