#!/usr/bin/env python3
"""Inventory static references to the legacy chat modules."""

from __future__ import annotations

import argparse
import ast
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import re


ROOTS = ("app", "tests", "scripts", "tools")
_APP_BASE = "app"
_LEGACY_BASE = f"{_APP_BASE}.services"
_PRODUCT_TASK_BASE = f"{_APP_BASE}.tasks.product"
_CELERY_TASK_BASE = "tasks.product"
_CHAT_API_BASE = f"{_APP_BASE}.api.v1"
_PROMPT_BASE = f"{_APP_BASE}.prompts"
TARGETS = (
    f"{_LEGACY_BASE}.agent",
    f"{_LEGACY_BASE}.conversation",
    f"{_LEGACY_BASE}.intent",
    f"{_LEGACY_BASE}.v2",
    f"{_PRODUCT_TASK_BASE}.tasks",
    f"{_CELERY_TASK_BASE}.recommend",
    f"{_CHAT_API_BASE}.chat",
    f"{_PROMPT_BASE}.intent_prompts",
    f"{_PROMPT_BASE}.test_intent_classifier",
)
_DOTTED_TARGET = re.compile(
    r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+"
)


@dataclass(frozen=True, slots=True)
class ImporterEntry:
    category: str
    kind: str
    line: int
    module: str
    path: str


@dataclass(frozen=True, slots=True)
class LegacyImporterInventory:
    entries: tuple[ImporterEntry, ...]
    files_scanned: int

    @property
    def direct_imports(self) -> int:
        return self._count("kind", "direct_import")

    @property
    def dynamic_imports(self) -> int:
        return self._count("kind", "dynamic_import")

    @property
    def string_targets(self) -> int:
        return self._count("kind", "string_target")

    @property
    def runtime_importers(self) -> int:
        return self._count("category", "runtime")

    @property
    def test_importers(self) -> int:
        return self._count("category", "test")

    @property
    def script_importers(self) -> int:
        return self._count("category", "script")

    @property
    def background_importers(self) -> int:
        return self._count("category", "background")

    def _count(self, field: str, value: str) -> int:
        return sum(
            1 for entry in self.entries if getattr(entry, field) == value
        )

    def to_payload(self) -> dict[str, object]:
        return {
            "schema_version": "legacy-chat-importers-v1",
            "roots": list(ROOTS),
            "targets": list(TARGETS),
            "files_scanned": self.files_scanned,
            "counts": {
                "background": self.background_importers,
                "direct_imports": self.direct_imports,
                "dynamic_imports": self.dynamic_imports,
                "runtime": self.runtime_importers,
                "script": self.script_importers,
                "string_targets": self.string_targets,
                "test": self.test_importers,
                "total": len(self.entries),
            },
            "entries": [asdict(entry) for entry in self.entries],
        }


def inventory_legacy_chat_importers(
    root: str | Path,
) -> LegacyImporterInventory:
    repository_root = Path(root).resolve(strict=True)
    source_paths = tuple(_iter_source_paths(repository_root))
    entries: list[ImporterEntry] = []

    for path in source_paths:
        relative_path = path.relative_to(repository_root)
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=relative_path.as_posix())
        entries.extend(
            _entries_for_tree(
                tree,
                relative_path=relative_path,
            )
        )

    entries.sort(
        key=lambda entry: (
            entry.path,
            entry.line,
            entry.module,
            entry.kind,
        )
    )
    return LegacyImporterInventory(
        entries=tuple(entries),
        files_scanned=len(source_paths),
    )


def write_inventory(
    root: str | Path,
    output_path: str | Path,
) -> LegacyImporterInventory:
    inventory = inventory_legacy_chat_importers(root)
    serialized = json.dumps(
        inventory.to_payload(),
        ensure_ascii=True,
        indent=2,
        sort_keys=True,
    )
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.tmp")
    temporary.write_text(f"{serialized}\n", encoding="utf-8")
    temporary.replace(output)
    return inventory


def _iter_source_paths(repository_root: Path) -> Iterable[Path]:
    paths: list[Path] = []
    for root_name in ROOTS:
        source_root = repository_root / root_name
        if not source_root.is_dir():
            continue
        for path in source_root.rglob("*.py"):
            relative_path = path.relative_to(repository_root)
            if "__pycache__" in relative_path.parts:
                continue
            if path.is_symlink() or not path.is_file():
                continue
            paths.append(path)
    yield from sorted(
        paths,
        key=lambda path: path.relative_to(repository_root).as_posix(),
    )


def _entries_for_tree(
    tree: ast.AST,
    *,
    relative_path: Path,
) -> list[ImporterEntry]:
    category = _category_for_path(relative_path)
    path = relative_path.as_posix()
    package = tuple(relative_path.with_suffix("").parts[:-1])
    entries: list[ImporterEntry] = []
    dynamic_literals: set[int] = set()

    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for module in _direct_import_targets(node, package):
                entries.append(
                    ImporterEntry(
                        category=category,
                        kind="direct_import",
                        line=node.lineno,
                        module=module,
                        path=path,
                    )
                )
        elif isinstance(node, ast.Call):
            dynamic = _literal_dynamic_import(node)
            if dynamic is None:
                continue
            literal_node, module = dynamic
            dynamic_literals.add(id(literal_node))
            if _is_target(module):
                entries.append(
                    ImporterEntry(
                        category=category,
                        kind="dynamic_import",
                        line=node.lineno,
                        module=module,
                        path=path,
                    )
                )

    docstrings = _docstring_literal_ids(tree)
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
        ):
            continue
        if id(node) in dynamic_literals or id(node) in docstrings:
            continue
        if _is_complete_target(node.value):
            entries.append(
                ImporterEntry(
                    category=category,
                    kind="string_target",
                    line=node.lineno,
                    module=node.value,
                    path=path,
                )
            )
    return entries


def _direct_import_targets(
    node: ast.Import | ast.ImportFrom,
    package: tuple[str, ...],
) -> tuple[str, ...]:
    if isinstance(node, ast.Import):
        return tuple(
            alias.name for alias in node.names if _is_target(alias.name)
        )

    base = _resolve_import_from(node, package)
    if _is_target(base):
        return (base,)

    modules = []
    for alias in node.names:
        if alias.name == "*":
            continue
        module = f"{base}.{alias.name}" if base else alias.name
        if _is_target(module):
            modules.append(module)
    return tuple(modules)


def _resolve_import_from(
    node: ast.ImportFrom,
    package: tuple[str, ...],
) -> str:
    if not node.level:
        return node.module or ""

    levels_up = node.level - 1
    if levels_up > len(package):
        return ""
    base = package[: len(package) - levels_up]
    module = tuple((node.module or "").split(".")) if node.module else ()
    return ".".join((*base, *module))


def _literal_dynamic_import(
    node: ast.Call,
) -> tuple[ast.Constant, str] | None:
    if not node.args:
        return None
    literal = node.args[0]
    if not (
        isinstance(literal, ast.Constant)
        and isinstance(literal.value, str)
    ):
        return None

    function = node.func
    is_import = (
        isinstance(function, ast.Name)
        and function.id in {"__import__", "import_module"}
    ) or (
        isinstance(function, ast.Attribute)
        and isinstance(function.value, ast.Name)
        and function.value.id == "importlib"
        and function.attr == "import_module"
    )
    if not is_import:
        return None
    return literal, literal.value


def _docstring_literal_ids(tree: ast.AST) -> set[int]:
    literal_ids: set[int] = set()
    owners = (
        ast.Module,
        ast.ClassDef,
        ast.FunctionDef,
        ast.AsyncFunctionDef,
    )
    for node in ast.walk(tree):
        if not isinstance(node, owners) or not node.body:
            continue
        first = node.body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            literal_ids.add(id(first.value))
    return literal_ids


def _is_complete_target(value: str) -> bool:
    target = value.removesuffix(".*")
    return (
        _DOTTED_TARGET.fullmatch(target) is not None
        and _is_target(target)
    )


def _is_target(module: str) -> bool:
    return any(
        module == target or module.startswith(f"{target}.")
        for target in TARGETS
    )


def _category_for_path(relative_path: Path) -> str:
    parts = relative_path.parts
    if parts[:2] == ("app", "tasks"):
        return "background"
    if parts[:1] == ("tests",):
        return "test"
    if parts[:1] in {("scripts",), ("tools",)}:
        return "script"
    return "runtime"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Inventory references to legacy chat modules.",
    )
    parser.add_argument("--root", default=".")
    parser.add_argument("--output", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    write_inventory(arguments.root, arguments.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
