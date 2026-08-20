from __future__ import annotations

import importlib
import json
from pathlib import Path


APP_BASE = "app"
LEGACY_BASE = f"{APP_BASE}.services"
LEGACY_AGENT = f"{LEGACY_BASE}.agent"
LEGACY_CONVERSATION = f"{LEGACY_BASE}.conversation"
LEGACY_INTENT = f"{LEGACY_BASE}.intent"
LEGACY_V2 = f"{LEGACY_BASE}.v2"
PRODUCT_TASK_BASE = f"{APP_BASE}.tasks.product"
LEGACY_PRODUCT_TASKS = f"{PRODUCT_TASK_BASE}.tasks"
CELERY_TASK_BASE = "tasks.product"
LEGACY_RECOMMEND_TASK = f"{CELERY_TASK_BASE}.recommend"
CHAT_API_BASE = f"{APP_BASE}.api.v1"
LEGACY_CHAT_ROUTE = f"{CHAT_API_BASE}.chat"
PROMPT_BASE = f"{APP_BASE}.prompts"
LEGACY_INTENT_PROMPTS = f"{PROMPT_BASE}.intent_prompts"
LEGACY_INTENT_CLASSIFIER = f"{PROMPT_BASE}.test_intent_classifier"
EXPECTED_TARGETS = [
    LEGACY_AGENT,
    LEGACY_CONVERSATION,
    LEGACY_INTENT,
    LEGACY_V2,
    LEGACY_PRODUCT_TASKS,
    LEGACY_RECOMMEND_TASK,
    LEGACY_CHAT_ROUTE,
    LEGACY_INTENT_PROMPTS,
    LEGACY_INTENT_CLASSIFIER,
]


def _inventory_module():
    return importlib.import_module(
        "tools.guide_gates.inventory_legacy_chat_importers"
    )


def _write_source(root: Path, relative_path: str, lines: list[str]) -> None:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_inventory_covers_import_forms_and_owner_categories(
    tmp_path: Path,
) -> None:
    inventory_module = _inventory_module()
    _write_source(
        tmp_path,
        "app/runtime.py",
        [f"import {LEGACY_AGENT}"],
    )
    _write_source(
        tmp_path,
        "app/tasks/worker.py",
        [f"from {LEGACY_V2} import presenter"],
    )
    _write_source(
        tmp_path,
        "tests/test_dynamic.py",
        [
            "import importlib",
            f'importlib.import_module("{LEGACY_INTENT}")',
        ],
    )
    _write_source(
        tmp_path,
        "scripts/probe.py",
        [f'__import__("{LEGACY_V2}.agent")'],
    )
    _write_source(
        tmp_path,
        "tools/celery_config.py",
        [f'CELERY_TARGET = "{LEGACY_AGENT}.ShoppingAgent"'],
    )

    result = inventory_module.inventory_legacy_chat_importers(tmp_path)

    assert result.direct_imports == 2
    assert result.dynamic_imports == 2
    assert result.string_targets == 1
    assert result.runtime_importers == 1
    assert result.test_importers == 1
    assert result.script_importers == 2
    assert result.background_importers == 1
    assert [
        (
            entry.path,
            entry.line,
            entry.module,
            entry.kind,
            entry.category,
        )
        for entry in result.entries
    ] == [
        (
            "app/runtime.py",
            1,
            LEGACY_AGENT,
            "direct_import",
            "runtime",
        ),
        (
            "app/tasks/worker.py",
            1,
            LEGACY_V2,
            "direct_import",
            "background",
        ),
        (
            "scripts/probe.py",
            1,
            f"{LEGACY_V2}.agent",
            "dynamic_import",
            "script",
        ),
        (
            "tests/test_dynamic.py",
            2,
            LEGACY_INTENT,
            "dynamic_import",
            "test",
        ),
        (
            "tools/celery_config.py",
            1,
            f"{LEGACY_AGENT}.ShoppingAgent",
            "string_target",
            "script",
        ),
    ]


def test_import_from_package_resolves_target_alias(
    tmp_path: Path,
) -> None:
    inventory_module = _inventory_module()
    _write_source(
        tmp_path,
        "app/consumer.py",
        [f"from {LEGACY_BASE} import conversation"],
    )

    result = inventory_module.inventory_legacy_chat_importers(tmp_path)

    assert result.direct_imports == 1
    assert result.entries[0].module == LEGACY_CONVERSATION


def test_relative_imports_inside_legacy_package_are_resolved(
    tmp_path: Path,
) -> None:
    inventory_module = _inventory_module()
    _write_source(
        tmp_path,
        "app/services/v2/agent.py",
        ["from .models import AnswerMode"],
    )

    result = inventory_module.inventory_legacy_chat_importers(tmp_path)

    assert result.direct_imports == 1
    assert result.entries[0].module == f"{LEGACY_V2}.models"


def test_dynamic_literal_is_not_double_counted_as_string_target(
    tmp_path: Path,
) -> None:
    inventory_module = _inventory_module()
    _write_source(
        tmp_path,
        "app/dynamic.py",
        [
            "from importlib import import_module",
            f'import_module("{LEGACY_INTENT}")',
        ],
    )

    result = inventory_module.inventory_legacy_chat_importers(tmp_path)

    assert result.dynamic_imports == 1
    assert result.string_targets == 0
    assert len(result.entries) == 1


def test_inventory_covers_dedicated_chat_and_background_targets_only(
    tmp_path: Path,
) -> None:
    inventory_module = _inventory_module()
    _write_source(
        tmp_path,
        "app/tasks/worker.py",
        [
            f'INCLUDE = ["{LEGACY_PRODUCT_TASKS}"]',
            f'TASK_ROUTES = {{"{LEGACY_PRODUCT_TASKS}.*": "product"}}',
            f'RECOMMEND_TASK = "{LEGACY_RECOMMEND_TASK}"',
            'NON_CHAT_TASK = "app.tasks.evaluation.tasks.*"',
            'OTHER_PRODUCT_TASK = "tasks.product.compare_prices"',
        ],
    )
    _write_source(
        tmp_path,
        "app/runtime.py",
        [
            f"from {LEGACY_CHAT_ROUTE} import router",
            f"from app.prompts import intent_prompts",
            (
                "from app.prompts.test_intent_classifier "
                "import IntentClassifier"
            ),
        ],
    )
    _write_source(
        tmp_path,
        "tools/task_registry.py",
        [
            f'TASK_GLOB = "{LEGACY_RECOMMEND_TASK}.*"',
            'UNRELATED_CHAT = "app.api.v1.search"',
            'UNRELATED_PROMPT = "app.prompts.product_prompts"',
        ],
    )

    result = inventory_module.inventory_legacy_chat_importers(tmp_path)

    assert result.direct_imports == 3
    assert result.string_targets == 4
    assert result.background_importers == 3
    assert [
        (entry.path, entry.line, entry.module, entry.kind, entry.category)
        for entry in result.entries
    ] == [
        (
            "app/runtime.py",
            1,
            LEGACY_CHAT_ROUTE,
            "direct_import",
            "runtime",
        ),
        (
            "app/runtime.py",
            2,
            LEGACY_INTENT_PROMPTS,
            "direct_import",
            "runtime",
        ),
        (
            "app/runtime.py",
            3,
            LEGACY_INTENT_CLASSIFIER,
            "direct_import",
            "runtime",
        ),
        (
            "app/tasks/worker.py",
            1,
            LEGACY_PRODUCT_TASKS,
            "string_target",
            "background",
        ),
        (
            "app/tasks/worker.py",
            2,
            f"{LEGACY_PRODUCT_TASKS}.*",
            "string_target",
            "background",
        ),
        (
            "app/tasks/worker.py",
            3,
            LEGACY_RECOMMEND_TASK,
            "string_target",
            "background",
        ),
        (
            "tools/task_registry.py",
            1,
            f"{LEGACY_RECOMMEND_TASK}.*",
            "string_target",
            "script",
        ),
    ]


def test_written_inventory_is_deterministic_and_contains_no_source_body(
    tmp_path: Path,
) -> None:
    inventory_module = _inventory_module()
    private_marker = "customer-private-source-body"
    _write_source(
        tmp_path,
        "app/z_last.py",
        [
            f'import {LEGACY_INTENT}',
            f'PRIVATE_NOTE = "{private_marker}"',
        ],
    )
    _write_source(
        tmp_path,
        "app/a_first.py",
        [f'CELERY_TARGET = "{LEGACY_AGENT}.ShoppingAgent"'],
    )
    first_output = tmp_path / "first.json"
    second_output = tmp_path / "second.json"

    first = inventory_module.write_inventory(tmp_path, first_output)
    second = inventory_module.write_inventory(tmp_path, second_output)

    assert first == second
    assert first_output.read_bytes() == second_output.read_bytes()
    serialized = first_output.read_text(encoding="utf-8")
    assert private_marker not in serialized
    assert str(tmp_path) not in serialized
    payload = json.loads(serialized)
    assert payload["schema_version"] == "legacy-chat-importers-v1"
    assert payload["roots"] == ["app", "tests", "scripts", "tools"]
    assert payload["targets"] == EXPECTED_TARGETS
    assert payload["counts"] == {
        "background": 0,
        "direct_imports": 1,
        "dynamic_imports": 0,
        "runtime": 2,
        "script": 0,
        "string_targets": 1,
        "test": 0,
        "total": 2,
    }
    assert list(payload["entries"][0]) == [
        "category",
        "kind",
        "line",
        "module",
        "path",
    ]
    assert payload["entries"] == sorted(
        payload["entries"],
        key=lambda entry: (
            entry["path"],
            entry["line"],
            entry["module"],
        ),
    )


def test_repository_has_no_legacy_chat_importers() -> None:
    inventory_module = _inventory_module()
    repository_root = Path(__file__).resolve().parents[3]

    result = inventory_module.inventory_legacy_chat_importers(
        repository_root
    )

    assert result.to_payload()["counts"] == {
        "background": 0,
        "direct_imports": 0,
        "dynamic_imports": 0,
        "runtime": 0,
        "script": 0,
        "string_targets": 0,
        "test": 0,
        "total": 0,
    }
    assert result.entries == ()
