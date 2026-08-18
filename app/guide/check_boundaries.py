#!/usr/bin/env python3
"""Enforce the architectural boundaries of the guide runtime."""

from __future__ import annotations

import argparse
import ast
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence


DEFAULT_ROOT = Path(__file__).resolve().parent
RUNTIME_PACKAGES = frozenset(
    {
        "understanding",
        "intent",
        "retrieval",
        "decision",
        "presentation",
        "feedback",
        "application",
        "adapters",
    }
)
RAW_CONTENT_FIELDS = frozenset(
    {
        "raw_description",
        "raw_review",
        "raw_reviews",
        "review_text",
        "reviews",
        "ocr_text",
        "raw_ocr",
        "raw_ocr_text",
    }
)
SCORING_TOKENS = frozenset(
    {"rank", "ranking", "score", "scorer", "scores", "scoring", "weight", "weights"}
)
LEXICON_TOKENS = frozenset(
    {"keyword", "keywords", "lexicon", "synonym", "synonyms", "vocab", "vocabulary"}
)


@dataclass(frozen=True, slots=True)
class Violation:
    layer: str
    file: str
    line: int
    rule: str
    detail: str


def _identifier_tokens(identifier: str) -> frozenset[str]:
    snake_case = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", identifier)
    return frozenset(token for token in re.split(r"[^a-z0-9]+", snake_case.lower()) if token)


def _module_matches(module: str, forbidden: str) -> bool:
    return module == forbidden or module.startswith(f"{forbidden}.")


def _imported_modules(
    node: ast.Import | ast.ImportFrom,
    package: tuple[str, ...],
) -> tuple[str, ...]:
    if isinstance(node, ast.Import):
        return tuple(alias.name for alias in node.names)

    if node.level:
        levels_up = node.level - 1
        if levels_up > len(package):
            return ()
        base = package[: len(package) - levels_up]
        module_parts = tuple((node.module or "").split(".")) if node.module else ()
        module = ".".join((*base, *module_parts))
    else:
        module = node.module or ""
    modules = [module] if module else []
    modules.extend(
        f"{module}.{alias.name}" if module else alias.name
        for alias in node.names
        if alias.name != "*"
    )
    return tuple(modules)


def _assigned_identifiers(target: ast.expr) -> Iterable[str]:
    if isinstance(target, ast.Name):
        yield target.id
    elif isinstance(target, ast.Attribute):
        yield target.attr
    elif isinstance(target, (ast.List, ast.Tuple)):
        for element in target.elts:
            yield from _assigned_identifiers(element)


def _literal_string(node: ast.expr) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


class _BoundaryVisitor(ast.NodeVisitor):
    def __init__(
        self,
        *,
        layer: str,
        file: str,
        package: tuple[str, ...],
        is_orchestrator: bool,
    ) -> None:
        self.layer = layer
        self.file = file
        self.package = package
        self.is_orchestrator = is_orchestrator
        self.violations: list[Violation] = []
        self._seen: set[tuple[str, int, str]] = set()

    def _add(self, node: ast.AST, rule: str, detail: str) -> None:
        line = getattr(node, "lineno", 0)
        key = (rule, line, detail)
        if key in self._seen:
            return
        self._seen.add(key)
        self.violations.append(
            Violation(
                layer=self.layer,
                file=self.file,
                line=line,
                rule=rule,
                detail=detail,
            )
        )

    def visit_Import(self, node: ast.Import) -> None:
        self._check_import(node)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        self._check_import(node)
        self.generic_visit(node)

    def _check_import(self, node: ast.Import | ast.ImportFrom) -> None:
        modules = _imported_modules(node, self.package)
        legacy_module = next(
            (module for module in modules if _module_matches(module, "app.services")),
            None,
        )
        if legacy_module:
            self._add(
                node,
                "FORBIDDEN_RUNTIME_IMPORT",
                f"guide runtime cannot import legacy module {legacy_module}",
            )

        tooling_module = next(
            (module for module in modules if _module_matches(module, "tools.evidence_audit")),
            None,
        )
        if tooling_module:
            self._add(
                node,
                "SEALED_TOOLING_IMPORT",
                f"guide runtime cannot import sealed tooling {tooling_module}",
            )

        adapter_module = next(
            (
                module
                for module in modules
                if _module_matches(module, "app.guide.adapters")
            ),
            None,
        )
        if self.layer == "presentation" and adapter_module:
            self._add(
                node,
                "PRESENTATION_ADAPTER_IMPORT",
                f"presentation cannot import concrete adapter {adapter_module}",
            )

    def _check_forbidden_module(self, node: ast.AST, module: str) -> None:
        if _module_matches(module, "app.services"):
            self._add(
                node,
                "FORBIDDEN_RUNTIME_IMPORT",
                f"guide runtime cannot import legacy module {module}",
            )
        if _module_matches(module, "tools.evidence_audit"):
            self._add(
                node,
                "SEALED_TOOLING_IMPORT",
                f"guide runtime cannot import sealed tooling {module}",
            )

    def visit_Name(self, node: ast.Name) -> None:
        if (
            self.layer == "decision"
            and isinstance(node.ctx, ast.Load)
            and node.id in RAW_CONTENT_FIELDS
        ):
            self._add(
                node,
                "DECISION_RAW_FIELD_ACCESS",
                f"decision cannot read raw content field {node.id}",
            )

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if (
            self.layer == "decision"
            and isinstance(node.ctx, ast.Load)
            and node.attr in RAW_CONTENT_FIELDS
        ):
            self._add(
                node,
                "DECISION_RAW_FIELD_ACCESS",
                f"decision cannot read raw content field {node.attr}",
            )
        self.generic_visit(node)

    def visit_Subscript(self, node: ast.Subscript) -> None:
        field = _literal_string(node.slice)
        if (
            self.layer == "decision"
            and isinstance(node.ctx, ast.Load)
            and field in RAW_CONTENT_FIELDS
        ):
            self._add(
                node,
                "DECISION_RAW_FIELD_ACCESS",
                f"decision cannot read raw content field {field}",
            )
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        field: str | None = None
        if (
            isinstance(node.func, ast.Attribute)
            and node.func.attr == "get"
            and node.args
        ):
            field = _literal_string(node.args[0])
        elif (
            isinstance(node.func, ast.Name)
            and node.func.id == "getattr"
            and len(node.args) >= 2
        ):
            field = _literal_string(node.args[1])

        if self.layer == "decision" and field in RAW_CONTENT_FIELDS:
            self._add(
                node,
                "DECISION_RAW_FIELD_ACCESS",
                f"decision cannot read raw content field {field}",
            )

        self._check_dynamic_import(node)
        self.generic_visit(node)

    def _check_dynamic_import(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Attribute):
            callee = node.func.attr
        elif isinstance(node.func, ast.Name):
            callee = node.func.id
        else:
            return
        if callee not in {"import_module", "__import__"} or not node.args:
            return
        module = _literal_string(node.args[0])
        if module is None:
            self._add(
                node,
                "DYNAMIC_IMPORT_NOT_ALLOWED",
                "guide runtime requires a literal dynamic import target",
            )
            return
        self._check_forbidden_module(node, module)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._check_function_name(node, node.name)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._check_function_name(node, node.name)
        self.generic_visit(node)

    def _check_function_name(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        name: str,
    ) -> None:
        tokens = _identifier_tokens(name)
        if self.layer == "retrieval" and "winner" in tokens:
            self._add(
                node,
                "RETRIEVAL_WINNER_LOGIC",
                f"retrieval cannot define winner operation {name}",
            )
        self._check_orchestrator_identifier(node, name)

    def visit_Assign(self, node: ast.Assign) -> None:
        for target in node.targets:
            self._check_assignment(node, target)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        self._check_assignment(node, node.target)
        self.generic_visit(node)

    def visit_NamedExpr(self, node: ast.NamedExpr) -> None:
        self._check_assignment(node, node.target)
        self.generic_visit(node)

    def _check_assignment(self, node: ast.AST, target: ast.expr) -> None:
        for identifier in _assigned_identifiers(target):
            tokens = _identifier_tokens(identifier)
            if self.layer == "retrieval" and "winner" in tokens:
                self._add(
                    node,
                    "RETRIEVAL_WINNER_LOGIC",
                    f"retrieval cannot assign winner state {identifier}",
                )
            self._check_orchestrator_identifier(node, identifier)

    def visit_Dict(self, node: ast.Dict) -> None:
        if self.layer == "retrieval":
            for key in node.keys:
                if key is None:
                    continue
                value = _literal_string(key)
                if value and "winner" in _identifier_tokens(value):
                    self._add(
                        node,
                        "RETRIEVAL_WINNER_LOGIC",
                        f"retrieval cannot produce winner field {value}",
                    )
        self.generic_visit(node)

    def _check_orchestrator_identifier(self, node: ast.AST, identifier: str) -> None:
        if not self.is_orchestrator:
            return
        tokens = _identifier_tokens(identifier)
        if tokens & SCORING_TOKENS:
            self._add(
                node,
                "ORCHESTRATOR_SCORING_LOGIC",
                f"orchestrator cannot define scoring identifier {identifier}",
            )
        if tokens & LEXICON_TOKENS:
            self._add(
                node,
                "ORCHESTRATOR_SEMANTIC_LEXICON",
                f"orchestrator cannot define semantic lexicon {identifier}",
            )


def check_boundaries(root: str | Path) -> list[Violation]:
    """Return deterministic, structured violations found below ``root``."""
    scan_root = Path(root).resolve()
    if not scan_root.is_dir():
        raise NotADirectoryError(f"guide root is not a directory: {scan_root}")

    violations: list[Violation] = []
    for path in sorted(scan_root.rglob("*.py")):
        relative_path = path.relative_to(scan_root)
        if "__pycache__" in relative_path.parts:
            continue

        file = relative_path.as_posix()
        layer = (
            relative_path.parts[0]
            if len(relative_path.parts) > 1
            and relative_path.parts[0] in RUNTIME_PACKAGES
            else "guide"
        )
        source = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(source, filename=file)
        except SyntaxError as exc:
            violations.append(
                Violation(
                    layer=layer,
                    file=file,
                    line=exc.lineno or 0,
                    rule="SYNTAX_ERROR",
                    detail=f"cannot parse Python source: {exc.msg}",
                )
            )
            continue

        visitor = _BoundaryVisitor(
            layer=layer,
            file=file,
            package=("app", "guide", *relative_path.parent.parts),
            is_orchestrator=(layer == "application"),
        )
        visitor.visit(tree)
        violations.extend(visitor.violations)

    return sorted(violations, key=lambda item: (item.file, item.line, item.rule, item.detail))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "root",
        nargs="?",
        type=Path,
        default=DEFAULT_ROOT,
        help="app/guide directory to scan",
    )
    args = parser.parse_args(argv)

    violations = check_boundaries(args.root)
    if not violations:
        print(f"Boundary check passed: {args.root}")
        return 0

    print(f"Boundary check failed with {len(violations)} violation(s):")
    for violation in violations:
        print(
            f"{violation.file}:{violation.line}: "
            f"[{violation.rule}] {violation.detail}"
        )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
