#!/usr/bin/env python3
"""Enforce the single Guide production path from HTTP to encoded SSE."""

from __future__ import annotations

import argparse
import ast
from collections import deque
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path


REPORT_SCHEMA = "guide-task11-single-path-architecture-v1"
_CHAT_PATHS = frozenset(
    {
        "/api/v1/chat/message",
        "/api/v1/chat/stream",
    }
)
_RAW_TEXT_FIELDS = frozenset(
    {
        "question_summary",
        "raw_question",
        "user_turn",
    }
)
_EVIDENCE_QUERY_FIELDS = frozenset(
    {
        "product_ids",
        "search",
        "safety_sensitive",
        "requested_dimensions",
        "product_identity_names",
    }
)
_PREPARED_EVIDENCE_SEARCH_FIELDS = frozenset(
    {
        "source_features",
        "meaning_features",
        "combined_features",
        "query_unigrams",
        "product_mention_features",
    }
)
_IMAGE_ROUTING_EVIDENCE_FIELDS = frozenset(
    {
        "bundle",
        "payloads",
        "observations",
        "anchor_topic",
    }
)
_SEMANTIC_PARSERS = frozenset(
    {
        "find_explicit_mentions",
        "parse_scenarios",
        "plan_code_owned_transitions",
        "plan_route_transition_operations",
        "plan_task",
        "revalidate_task_plan",
        "resolve_product_knowledge_dimensions",
    }
)
_POST_ROUTER_TASK_MUTATORS = frozenset({
    "_bind_route_products",
    "plan_task",
    "revalidate_task_plan",
})
_BUSINESS_IMPORT_PREFIXES = (
    "app.guide.intent",
    "app.guide.feedback",
    "app.guide.application.conversation_state_reducer",
    "app.guide.application.execution_contracts",
    "app.guide.application.reducer",
)
_SERIALIZATION_TOKENS = frozenset(
    {
        "collect",
        "dump",
        "encode",
        "materialize",
        "project",
        "serialize",
    }
)
_SNAPSHOT_FIELDS = frozenset(
    {
        "session_id",
        "version",
        "profile_owner",
        "session_profile",
        "active_owner",
        "active_focus",
        "recommendation_slot",
        "product_slot",
        "image_slot",
        "consultation_slot",
        "knowledge_slot",
        "reply_slot",
    }
)
_NESTED_SLOT_FIELDS = {
    "RecommendationSlotState": frozenset(
        {
            "kind",
            "query_context",
            "candidates",
            "empty_result",
            "focused_candidate_ordinal",
        }
    ),
    "ProductSlotState": frozenset(
        {
            "kind",
            "products",
            "focused_product_id",
            "focused_evidence_ids",
        }
    ),
    "ImageSlotState": frozenset(
        {
            "kind",
            "confirmed_products",
            "focused_image_ordinal",
        }
    ),
    "ConsultationSlotState": frozenset({"kind", "state"}),
    "KnowledgeSlotState": frozenset(
        {"kind", "question", "evidence_ids"}
    ),
    "PendingClarificationSlot": frozenset({"kind", "value"}),
    "PendingReplySlot": frozenset({"kind", "value"}),
    "ActiveFocus": frozenset({"slot", "object_id", "ordinal"}),
}
_REPLY_SLOT_MEMBERS = frozenset(
    {"PendingClarificationSlot", "PendingReplySlot"}
)
_LEGACY_REQUEST_FIELDS = frozenset(
    {"image_context", "image_results", "images"}
)
_PROCESSOR_INPUT_FIELDS = frozenset(
    {
        "turn_identity",
        "understanding",
        "decision",
        "current_snapshot",
        "routing_evidence",
    }
)
_FORBIDDEN_PROCESSOR_DEPENDENCY_TOKENS = frozenset(
    {
        "callback",
        "callable",
        "factory",
        "processor",
        "registry",
    }
)
_FORBIDDEN_PRE_ROUTING_DEPENDENCY_TOKENS = frozenset(
    {
        "authorizer",
        "bundle",
        "bundles",
        "collector",
    }
)
_FORBIDDEN_PROCESSOR_PRODUCT_RESOLUTION_METHODS = frozenset(
    {
        "resolve_product_bindings",
        "resolve_product_resolution",
    }
)
_PROCESSOR_ENTRY_OBSERVER = (
    "app.guide.application.execution_contracts."
    "notify_processor_entry"
)
_LEGACY_PUBLIC_CAPABILITIES = frozenset(
    {
        "ChatOwner",
        "GuideOrchestrator",
        "classify_chat_owner",
        "collect_guide_chat_response",
    }
)
_DORMANT_COMPATIBILITY_CAPABILITIES = frozenset(
    {
        "bind_execution_profile_owner",
        "from_user_turn",
        "understand_text",
    }
)
_FORBIDDEN_LEGACY_MODULE_PATHS = frozenset(
    {
        "app/guide/adapters/llm/deepseek_two_stage_intent.py",
        "app/guide/adapters/llm/intent_detail_prompt.py",
        "app/guide/adapters/llm/intent_route_prompt.py",
        "app/guide/adapters/llm/siliconflow_two_stage_intent.py",
        "app/guide/intent/budget_revision_planning.py",
        "app/guide/intent/consultation_planning.py",
        "app/guide/intent/skin_revision_planning.py",
        "app/guide/understanding/parallel_understanding.py",
        "app/guide/understanding/semantic_detail_contracts.py",
        "app/guide/understanding/two_stage_semantic.py",
        "tools/guide_gates/two_stage_intent_gate.py",
    }
)
_RUNTIME_REGISTRATION_WRITER = (
    "tools.guide_gates.attempt_ledger",
    "register_runtime_bound_attempt",
)
_RUNTIME_REGISTRATION_OWNER = (
    "tools/guide_gates/run_bound_runtime.py",
    "run_bound_runtime",
)


@dataclass(frozen=True, slots=True)
class ArchitectureManifest:
    production_roots: tuple[str, ...]
    canonical_calls: Mapping[str, tuple[str, str]]
    processor_roots: tuple[str, ...]
    post_router_roots: tuple[str, ...]
    adapter_packages: tuple[str, ...]
    snapshot_contract: str
    request_contract: str
    composition_roots: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ArchitectureViolation:
    rule: str
    file: str
    line: int
    detail: str


@dataclass(frozen=True, slots=True)
class ArchitectureReport:
    inspected_modules: tuple[str, ...]
    violations: tuple[ArchitectureViolation, ...]

    @property
    def passed(self) -> bool:
        return not self.violations

    def to_payload(self) -> dict[str, object]:
        return {
            "schema_version": REPORT_SCHEMA,
            "passed": self.passed,
            "inspected_module_count": len(self.inspected_modules),
            "inspected_modules": list(self.inspected_modules),
            "violation_count": len(self.violations),
            "violations": [
                asdict(violation) for violation in self.violations
            ],
        }


@dataclass(frozen=True, slots=True)
class _FunctionRecord:
    identifier: str
    module: str
    qualname: str
    class_name: str | None
    node: ast.FunctionDef | ast.AsyncFunctionDef


@dataclass(frozen=True, slots=True)
class _CallSite:
    module: str
    scope: str
    file: str
    line: int
    callee: str
    node: ast.Call


@dataclass(slots=True)
class _ModuleRecord:
    module: str
    file: str
    path: Path
    tree: ast.Module
    imports: dict[str, str]
    functions: dict[str, _FunctionRecord]
    classes: dict[str, ast.ClassDef]
    calls: tuple[_CallSite, ...]


class _DefinitionCollector(ast.NodeVisitor):
    def __init__(self, module: str) -> None:
        self._module = module
        self._scope: list[str] = []
        self.functions: dict[str, _FunctionRecord] = {}
        self.classes: dict[str, ast.ClassDef] = {}
        self.calls: list[_CallSite] = []
        self.file = ""

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        qualname = ".".join((*self._scope, node.name))
        self.classes[qualname] = node
        self._scope.append(node.name)
        self.generic_visit(node)
        self._scope.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_AsyncFunctionDef(
        self,
        node: ast.AsyncFunctionDef,
    ) -> None:
        self._visit_function(node)

    def _visit_function(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
    ) -> None:
        qualname = ".".join((*self._scope, node.name))
        class_name = self._scope[-1] if self._scope else None
        identifier = f"{self._module}:{qualname}"
        self.functions[qualname] = _FunctionRecord(
            identifier=identifier,
            module=self._module,
            qualname=qualname,
            class_name=class_name,
            node=node,
        )
        self._scope.append(node.name)
        self.generic_visit(node)
        self._scope.pop()

    def visit_Call(self, node: ast.Call) -> None:
        self.calls.append(
            _CallSite(
                module=self._module,
                scope=".".join(self._scope),
                file=self.file,
                line=node.lineno,
                callee=_expression_name(node.func),
                node=node,
            )
        )
        self.generic_visit(node)


class _FunctionBodyCollector(ast.NodeVisitor):
    def __init__(
        self,
        root: ast.FunctionDef | ast.AsyncFunctionDef,
    ) -> None:
        self._root = root
        self.nodes: list[ast.AST] = []

    def collect(self) -> tuple[ast.AST, ...]:
        for statement in self._root.body:
            self.visit(statement)
        return tuple(self.nodes)

    def generic_visit(self, node: ast.AST) -> None:
        self.nodes.append(node)
        super().generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.nodes.append(node)

    def visit_AsyncFunctionDef(
        self,
        node: ast.AsyncFunctionDef,
    ) -> None:
        self.nodes.append(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.nodes.append(node)


def _expression_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _expression_name(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    if isinstance(node, ast.Subscript):
        base = _expression_name(node.value)
        return f"{base}[]" if base else "[]"
    if isinstance(node, ast.Call):
        base = _expression_name(node.func)
        return f"{base}()" if base else "()"
    return ""


def _resolve_module_alias(
    module: _ModuleRecord,
    expression: str,
) -> str:
    if not expression:
        return expression
    first, separator, suffix = expression.partition(".")
    imported = module.imports.get(first)
    if imported is None:
        return expression
    return f"{imported}{separator}{suffix}" if separator else imported


def _target_names(node: ast.AST) -> tuple[str, ...]:
    if isinstance(node, ast.Name):
        return (node.id,)
    if isinstance(node, ast.Attribute):
        return (node.attr,)
    if isinstance(node, (ast.Tuple, ast.List)):
        return tuple(
            name
            for item in node.elts
            for name in _target_names(item)
        )
    return ()


def _module_name(relative_path: Path) -> str:
    parts = list(relative_path.with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _import_aliases(
    tree: ast.Module,
    *,
    module: str,
) -> dict[str, str]:
    aliases: dict[str, str] = {}
    package = module.split(".")[:-1]
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for item in node.names:
                local = item.asname or item.name.split(".")[0]
                aliases[local] = item.name
        elif isinstance(node, ast.ImportFrom):
            imported_module = _resolve_import_from(
                node,
                package=package,
            )
            for item in node.names:
                if item.name == "*":
                    continue
                local = item.asname or item.name
                aliases[local] = ".".join(
                    part
                    for part in (imported_module, item.name)
                    if part
                )
    return aliases


def _resolve_import_from(
    node: ast.ImportFrom,
    *,
    package: Sequence[str],
) -> str:
    if node.level == 0:
        return node.module or ""
    levels_up = node.level - 1
    if levels_up > len(package):
        return node.module or ""
    base = tuple(package[: len(package) - levels_up])
    suffix = tuple((node.module or "").split(".")) if node.module else ()
    return ".".join((*base, *suffix))


def _load_modules(
    root: Path,
) -> tuple[dict[str, _ModuleRecord], list[ArchitectureViolation]]:
    modules: dict[str, _ModuleRecord] = {}
    violations: list[ArchitectureViolation] = []
    app_root = root / "app"
    if not app_root.is_dir():
        return modules, [
            ArchitectureViolation(
                rule="MISSING_PRODUCTION_ROOT",
                file="app",
                line=1,
                detail="repository has no app package",
            )
        ]
    for path in sorted(app_root.rglob("*.py")):
        relative_path = path.relative_to(root)
        if "__pycache__" in relative_path.parts or path.is_symlink():
            continue
        module = _module_name(relative_path)
        source = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(source, filename=relative_path.as_posix())
        except SyntaxError as exc:
            violations.append(
                ArchitectureViolation(
                    rule="SYNTAX_ERROR",
                    file=relative_path.as_posix(),
                    line=exc.lineno or 1,
                    detail=exc.msg,
                )
            )
            continue
        collector = _DefinitionCollector(module)
        collector.file = relative_path.as_posix()
        collector.visit(tree)
        modules[module] = _ModuleRecord(
            module=module,
            file=relative_path.as_posix(),
            path=path,
            tree=tree,
            imports=_import_aliases(tree, module=module),
            functions=collector.functions,
            classes=collector.classes,
            calls=tuple(collector.calls),
        )
    return modules, violations


def _function_index(
    modules: Mapping[str, _ModuleRecord],
) -> dict[str, _FunctionRecord]:
    return {
        record.identifier: record
        for module in modules.values()
        for record in module.functions.values()
    }


def _class_index(
    modules: Mapping[str, _ModuleRecord],
) -> dict[str, tuple[_ModuleRecord, ast.ClassDef]]:
    return {
        f"{module.module}:{qualname}": (module, node)
        for module in modules.values()
        for qualname, node in module.classes.items()
    }


def _add(
    violations: list[ArchitectureViolation],
    *,
    rule: str,
    module: _ModuleRecord | None,
    line: int,
    detail: str,
    file: str | None = None,
) -> None:
    violations.append(
        ArchitectureViolation(
            rule=rule,
            file=file or (module.file if module is not None else "app"),
            line=max(1, line),
            detail=detail,
        )
    )


def _discover_chat_routes(
    modules: Mapping[str, _ModuleRecord],
) -> tuple[tuple[str, str, _ModuleRecord, int], ...]:
    discovered: list[tuple[str, str, _ModuleRecord, int]] = []
    for module in modules.values():
        for function in module.functions.values():
            for decorator in function.node.decorator_list:
                if not isinstance(decorator, ast.Call):
                    continue
                method = _expression_name(decorator.func).rsplit(".", 1)[-1]
                if method not in {"api_route", "post"} or not decorator.args:
                    continue
                path_node = decorator.args[0]
                if not (
                    isinstance(path_node, ast.Constant)
                    and isinstance(path_node.value, str)
                    and path_node.value in _CHAT_PATHS
                ):
                    continue
                discovered.append(
                    (
                        function.identifier,
                        path_node.value,
                        module,
                        function.node.lineno,
                    )
                )
    return tuple(discovered)


def _check_roots(
    modules: Mapping[str, _ModuleRecord],
    manifest: ArchitectureManifest,
    violations: list[ArchitectureViolation],
) -> None:
    discovered = _discover_chat_routes(modules)
    declared = set(manifest.production_roots)
    for identifier, path, module, line in discovered:
        if identifier not in declared:
            _add(
                violations,
                rule="UNLISTED_PRODUCTION_ROOT",
                module=module,
                line=line,
                detail=f"{identifier} ({path})",
            )
    if len(discovered) > 1:
        for identifier, path, module, line in discovered:
            if path == "/api/v1/chat/stream":
                continue
            _add(
                violations,
                rule="MULTIPLE_CHAT_ROUTES",
                module=module,
                line=line,
                detail=f"{identifier} exposes {path}",
            )
    functions = _function_index(modules)
    for identifier in (*manifest.production_roots, *manifest.composition_roots):
        if identifier in functions:
            continue
        module_name = identifier.split(":", 1)[0]
        module = modules.get(module_name)
        _add(
            violations,
            rule="MISSING_PRODUCTION_ROOT",
            module=module,
            line=1,
            detail=identifier,
        )


def _check_public_static_mounts(
    modules: Mapping[str, _ModuleRecord],
    violations: list[ArchitectureViolation],
) -> None:
    def resolve_string(
        node: ast.expr,
        bindings: Mapping[str, str],
    ) -> str | None:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.Name):
            return bindings.get(node.id)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            left = resolve_string(node.left, bindings)
            right = resolve_string(node.right, bindings)
            if left is not None and right is not None:
                return left + right
        return None

    for module in modules.values():
        for function in module.functions.values():
            for decorator in function.node.decorator_list:
                if (
                    not isinstance(decorator, ast.Call)
                    or _expression_name(decorator.func).rsplit(".", 1)[-1]
                    not in {"get", "route", "api_route"}
                    or not decorator.args
                ):
                    continue
                route_path = resolve_string(decorator.args[0], {})
                if (
                    route_path is None
                    or not route_path.endswith(
                        "/guide-demo-fixture.js"
                    )
                ):
                    continue
                _add(
                    violations,
                    rule="PUBLIC_FIXTURE_TRANSPORT",
                    module=module,
                    line=decorator.lineno,
                    detail=route_path,
                )
        nested_call_ids = {
            id(node)
            for statement in module.tree.body
            if isinstance(
                statement,
                (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef),
            )
            for node in ast.walk(statement)
            if isinstance(node, ast.Call)
        }
        for call in module.calls:
            if _expression_name(call.node.func).rsplit(".", 1)[-1] != "mount":
                continue
            bindings: dict[str, str] = {}
            if id(call.node) not in nested_call_ids:
                call_position = (call.node.lineno, call.node.col_offset)
                for statement in module.tree.body:
                    statement_position = (
                        statement.lineno,
                        statement.col_offset,
                    )
                    if statement_position >= call_position:
                        break
                    if not isinstance(
                        statement,
                        (ast.Assign, ast.AnnAssign),
                    ):
                        continue
                    targets = (
                        statement.targets
                        if isinstance(statement, ast.Assign)
                        else (statement.target,)
                    )
                    value = resolve_string(statement.value, bindings)
                    for target in targets:
                        if not isinstance(target, ast.Name):
                            continue
                        if value is None:
                            bindings.pop(target.id, None)
                        else:
                            bindings[target.id] = value
            path_node = (
                call.node.args[0]
                if call.node.args
                else next(
                    (
                        keyword.value
                        for keyword in call.node.keywords
                        if keyword.arg == "path"
                    ),
                    None,
                )
            )
            resolved_path = (
                resolve_string(path_node, bindings)
                if path_node is not None
                else None
            )
            if (
                resolved_path is None
                or resolved_path.rstrip("/") == "/static"
            ):
                detail = (
                    "/static root mount exposes unscoped HTML"
                    if resolved_path is not None
                    else (
                        "unresolved mount path may expose the /static root"
                    )
                )
                _add(
                    violations,
                    rule="PUBLIC_STATIC_HTML_BYPASS",
                    module=module,
                    line=call.node.lineno,
                    detail=detail,
                )


def _callee_matches(callee: str, symbol: str) -> bool:
    return callee == symbol or callee.endswith(f".{symbol}")


def _trusted_module_imports(
    module: _ModuleRecord,
) -> dict[str, str]:
    imports: dict[str, str] = {}
    invalid: set[str] = set()
    package = module.module.split(".")[:-1]
    for node in module.tree.body:
        imported: dict[str, str] = {}
        rebound: set[str] = set()
        if isinstance(node, ast.Import):
            imported = {
                item.asname or item.name.split(".")[0]: item.name
                for item in node.names
            }
        elif isinstance(node, ast.ImportFrom):
            imported_module = _resolve_import_from(
                node,
                package=package,
            )
            imported = {
                item.asname or item.name: ".".join(
                    part
                    for part in (imported_module, item.name)
                    if part
                )
                for item in node.names
                if item.name != "*"
            }
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            rebound.add(node.name)
        elif isinstance(node, ast.ClassDef):
            rebound.add(node.name)
        elif isinstance(node, ast.Assign):
            rebound.update(
                name
                for target in node.targets
                for name in _target_names(target)
            )
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
            rebound.update(_target_names(node.target))

        for name, target in imported.items():
            if name in imports or name in invalid:
                invalid.add(name)
                imports.pop(name, None)
            else:
                imports[name] = target
        for name in rebound:
            invalid.add(name)
            imports.pop(name, None)

    class ConditionalRebindingVisitor(ast.NodeVisitor):
        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            invalid.add(node.name)

        def visit_AsyncFunctionDef(
            self,
            node: ast.AsyncFunctionDef,
        ) -> None:
            invalid.add(node.name)

        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            invalid.add(node.name)

        def visit_Lambda(self, node: ast.Lambda) -> None:
            del node

        def visit_Import(self, node: ast.Import) -> None:
            invalid.update(
                alias.asname or alias.name.split(".", 1)[0]
                for alias in node.names
            )

        def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
            invalid.update(
                alias.asname or alias.name
                for alias in node.names
            )

        def visit_Name(self, node: ast.Name) -> None:
            if isinstance(node.ctx, (ast.Store, ast.Del)):
                invalid.add(node.id)

        def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
            if isinstance(node.name, str):
                invalid.add(node.name)
            if node.type is not None:
                self.visit(node.type)
            for statement in node.body:
                self.visit(statement)

        def visit_MatchAs(self, node: ast.MatchAs) -> None:
            if node.name is not None:
                invalid.add(node.name)
            if node.pattern is not None:
                self.visit(node.pattern)

        def visit_MatchStar(self, node: ast.MatchStar) -> None:
            if node.name is not None:
                invalid.add(node.name)

        def visit_MatchMapping(self, node: ast.MatchMapping) -> None:
            if node.rest is not None:
                invalid.add(node.rest)
            self.generic_visit(node)

    rebinding_visitor = ConditionalRebindingVisitor()
    for node in module.tree.body:
        if not isinstance(node, (ast.Import, ast.ImportFrom)):
            rebinding_visitor.visit(node)
    for name in invalid:
        imports.pop(name, None)
    return imports


def _function_local_bindings(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
) -> set[str]:
    bindings = {
        argument.arg
        for argument in (
            *function.args.posonlyargs,
            *function.args.args,
            *function.args.kwonlyargs,
        )
    }
    if function.args.vararg is not None:
        bindings.add(function.args.vararg.arg)
    if function.args.kwarg is not None:
        bindings.add(function.args.kwarg.arg)

    class BindingVisitor(ast.NodeVisitor):
        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            bindings.add(node.name)

        def visit_AsyncFunctionDef(
            self,
            node: ast.AsyncFunctionDef,
        ) -> None:
            bindings.add(node.name)

        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            bindings.add(node.name)

        def visit_Lambda(self, node: ast.Lambda) -> None:
            del node

        def visit_Name(self, node: ast.Name) -> None:
            if isinstance(node.ctx, (ast.Store, ast.Del)):
                bindings.add(node.id)

        def visit_Import(self, node: ast.Import) -> None:
            bindings.update(
                alias.asname or alias.name.split(".", 1)[0]
                for alias in node.names
            )

        def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
            bindings.update(
                alias.asname or alias.name
                for alias in node.names
            )

        def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
            if isinstance(node.name, str):
                bindings.add(node.name)
            if node.type is not None:
                self.visit(node.type)
            for statement in node.body:
                self.visit(statement)

        def visit_MatchAs(self, node: ast.MatchAs) -> None:
            if node.name is not None:
                bindings.add(node.name)
            if node.pattern is not None:
                self.visit(node.pattern)

        def visit_MatchStar(self, node: ast.MatchStar) -> None:
            if node.name is not None:
                bindings.add(node.name)

        def visit_MatchMapping(self, node: ast.MatchMapping) -> None:
            if node.rest is not None:
                bindings.add(node.rest)
            self.generic_visit(node)

    visitor = BindingVisitor()
    for statement in function.body:
        visitor.visit(statement)
    return bindings


_UNKNOWN_STATIC_VALUE = object()


def _static_value(
    value: ast.expr,
    *,
    known_false_names: Collection[str],
    known_false_attributes: Collection[str],
) -> object:
    if isinstance(value, ast.Name) and value.id in known_false_names:
        return False
    if (
        isinstance(value, ast.Attribute)
        and _expression_name(value) in known_false_attributes
    ):
        return False
    try:
        return ast.literal_eval(value)
    except (TypeError, ValueError):
        return _UNKNOWN_STATIC_VALUE


def _static_truth(
    value: ast.expr,
    *,
    known_false_names: Collection[str] = (),
    known_false_attributes: Collection[str] = (),
) -> bool | None:
    if isinstance(value, ast.UnaryOp) and isinstance(value.op, ast.Not):
        operand = _static_truth(
            value.operand,
            known_false_names=known_false_names,
            known_false_attributes=known_false_attributes,
        )
        return None if operand is None else not operand
    if isinstance(value, ast.BoolOp):
        truths = tuple(
            _static_truth(
                item,
                known_false_names=known_false_names,
                known_false_attributes=known_false_attributes,
            )
            for item in value.values
        )
        if isinstance(value.op, ast.And):
            if False in truths:
                return False
            return True if all(item is True for item in truths) else None
        if True in truths:
            return True
        return False if all(item is False for item in truths) else None
    if isinstance(value, ast.Compare):
        operands = (value.left, *value.comparators)
        resolved = tuple(
            _static_value(
                item,
                known_false_names=known_false_names,
                known_false_attributes=known_false_attributes,
            )
            for item in operands
        )
        if _UNKNOWN_STATIC_VALUE in resolved:
            return None
        try:
            comparisons = tuple(
                (
                    left == right
                    if isinstance(operator, ast.Eq)
                    else left != right
                    if isinstance(operator, ast.NotEq)
                    else left < right
                    if isinstance(operator, ast.Lt)
                    else left <= right
                    if isinstance(operator, ast.LtE)
                    else left > right
                    if isinstance(operator, ast.Gt)
                    else left >= right
                    if isinstance(operator, ast.GtE)
                    else left is right
                    if isinstance(operator, ast.Is)
                    else left is not right
                    if isinstance(operator, ast.IsNot)
                    else left in right
                    if isinstance(operator, ast.In)
                    else left not in right
                    if isinstance(operator, ast.NotIn)
                    else _UNKNOWN_STATIC_VALUE
                )
                for left, operator, right in zip(
                    resolved[:-1],
                    value.ops,
                    resolved[1:],
                    strict=True,
                )
            )
        except (TypeError, ValueError):
            return None
        if _UNKNOWN_STATIC_VALUE in comparisons:
            return None
        return all(comparisons)
    resolved = _static_value(
        value,
        known_false_names=known_false_names,
        known_false_attributes=known_false_attributes,
    )
    return (
        None
        if resolved is _UNKNOWN_STATIC_VALUE
        else bool(resolved)
    )


def _statements_guaranteed_to_terminate(
    statements: Sequence[ast.stmt],
    *,
    known_false_names: Collection[str],
    known_false_attributes: Collection[str],
) -> bool:
    return any(
        _statement_guaranteed_to_terminate(
            statement,
            known_false_names=known_false_names,
            known_false_attributes=known_false_attributes,
        )
        for statement in statements
    )


def _statement_guaranteed_to_terminate(
    statement: ast.stmt,
    *,
    known_false_names: Collection[str],
    known_false_attributes: Collection[str],
) -> bool:
    if isinstance(
        statement,
        (ast.Break, ast.Continue, ast.Raise, ast.Return),
    ):
        return True
    if not isinstance(statement, ast.If):
        return False
    truth = _static_truth(
        statement.test,
        known_false_names=known_false_names,
        known_false_attributes=known_false_attributes,
    )
    if truth is True:
        return _statements_guaranteed_to_terminate(
            statement.body,
            known_false_names=known_false_names,
            known_false_attributes=known_false_attributes,
        )
    if truth is False:
        return _statements_guaranteed_to_terminate(
            statement.orelse,
            known_false_names=known_false_names,
            known_false_attributes=known_false_attributes,
        )
    return bool(statement.orelse) and all(
        _statements_guaranteed_to_terminate(
            branch,
            known_false_names=known_false_names,
            known_false_attributes=known_false_attributes,
        )
        for branch in (statement.body, statement.orelse)
    )


def _executable_call_nodes(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    *,
    known_false_names: Collection[str] = (),
    known_false_attributes: Collection[str] = (),
) -> tuple[ast.Call, ...]:
    calls: list[ast.Call] = []

    class ExecutableCallVisitor(ast.NodeVisitor):
        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            del node

        def visit_AsyncFunctionDef(
            self,
            node: ast.AsyncFunctionDef,
        ) -> None:
            del node

        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            del node

        def visit_Lambda(self, node: ast.Lambda) -> None:
            del node

        def visit_If(self, node: ast.If) -> None:
            truth = _static_truth(
                node.test,
                known_false_names=known_false_names,
                known_false_attributes=known_false_attributes,
            )
            self.visit(node.test)
            if truth is not False:
                self.visit_statements(node.body)
            if truth is not True:
                self.visit_statements(node.orelse)

        def visit_While(self, node: ast.While) -> None:
            truth = _static_truth(
                node.test,
                known_false_names=known_false_names,
                known_false_attributes=known_false_attributes,
            )
            self.visit(node.test)
            if truth is not False:
                self.visit_statements(node.body)
            self.visit_statements(node.orelse)

        def visit_For(self, node: ast.For) -> None:
            self.visit(node.target)
            self.visit(node.iter)
            self.visit_statements(node.body)
            self.visit_statements(node.orelse)

        def visit_AsyncFor(self, node: ast.AsyncFor) -> None:
            self.visit(node.target)
            self.visit(node.iter)
            self.visit_statements(node.body)
            self.visit_statements(node.orelse)

        def visit_Try(self, node: ast.Try) -> None:
            self.visit_statements(node.body)
            for handler in node.handlers:
                if handler.type is not None:
                    self.visit(handler.type)
                self.visit_statements(handler.body)
            self.visit_statements(node.orelse)
            self.visit_statements(node.finalbody)

        def visit_Call(self, node: ast.Call) -> None:
            calls.append(node)
            self.generic_visit(node)

        def visit_statements(
            self,
            statements: Sequence[ast.stmt],
        ) -> None:
            for statement in statements:
                self.visit(statement)
                if isinstance(
                    statement,
                    (ast.Break, ast.Continue, ast.Raise, ast.Return),
                ):
                    break
                if _statement_guaranteed_to_terminate(
                    statement,
                    known_false_names=known_false_names,
                    known_false_attributes=known_false_attributes,
                ):
                    break

    visitor = ExecutableCallVisitor()
    visitor.visit_statements(function.body)
    return tuple(calls)


def _canonical_call_sites(
    modules: Mapping[str, _ModuleRecord],
    *,
    boundary: str,
    symbol: str,
) -> tuple[_CallSite, ...]:
    matches: list[_CallSite] = []
    for module in modules.values():
        trusted_imports = _trusted_module_imports(module)
        for record in module.functions.values():
            local_bindings = _function_local_bindings(record.node)
            known_false_names = {
                name
                for name, imported in trusted_imports.items()
                if (
                    imported == "typing.TYPE_CHECKING"
                    and name not in local_bindings
                )
            }
            known_false_attributes = {
                f"{name}.TYPE_CHECKING"
                for name, imported in trusted_imports.items()
                if imported == "typing" and name not in local_bindings
            }
            for call in _executable_call_nodes(
                record.node,
                known_false_names=known_false_names,
                known_false_attributes=known_false_attributes,
            ):
                callee = _expression_name(call.func)
                resolved: str | None = None
                if isinstance(call.func, ast.Name):
                    if call.func.id not in local_bindings:
                        resolved = trusted_imports.get(call.func.id)
                elif isinstance(call.func, ast.Attribute):
                    first = callee.split(".", 1)[0]
                    if (
                        first in trusted_imports
                        and first not in local_bindings
                    ):
                        resolved = _resolve_module_alias(module, callee)
                    elif boundary == "cas":
                        resolved = callee
                if resolved is None or not _callee_matches(
                    resolved,
                    symbol,
                ):
                    continue
                matches.append(
                    _CallSite(
                        module=module.module,
                        scope=record.qualname,
                        file=module.file,
                        line=call.lineno,
                        callee=callee,
                        node=call,
                    )
                )
    return tuple(matches)


def _check_canonical_calls(
    modules: Mapping[str, _ModuleRecord],
    manifest: ArchitectureManifest,
    violations: list[ArchitectureViolation],
) -> None:
    for boundary, (symbol, owner) in manifest.canonical_calls.items():
        matches = _canonical_call_sites(
            modules,
            boundary=boundary,
            symbol=symbol,
        )
        owner_module_name = owner.split(":", 1)[0]
        owner_module = modules.get(owner_module_name)
        if len(matches) != 1:
            location = matches[0] if matches else None
            _add(
                violations,
                rule="CANONICAL_CALL_CARDINALITY",
                module=(
                    modules.get(location.module)
                    if location is not None
                    else owner_module
                ),
                line=location.line if location is not None else 1,
                detail=(
                    f"{boundary} expected exactly one call to {symbol}; "
                    f"observed {len(matches)}"
                ),
            )
        for call in matches:
            identifier = f"{call.module}:{call.scope}"
            if identifier == owner:
                continue
            _add(
                violations,
                rule="NONCANONICAL_OWNER_CALLSITE",
                module=modules[call.module],
                line=call.line,
                detail=(
                    f"{boundary} call to {symbol} is owned by "
                    f"{identifier}, expected {owner}"
                ),
            )


def _function_nodes(record: _FunctionRecord) -> tuple[ast.AST, ...]:
    return _FunctionBodyCollector(record.node).collect()


def _simple_local_assignments(
    record: _FunctionRecord,
    *,
    before: ast.AST | None = None,
) -> dict[str, ast.AST]:
    assignments: dict[str, ast.AST] = {}
    before_position = (
        (before.lineno, before.col_offset)
        if before is not None
        else None
    )
    for node in _function_nodes(record):
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            value = node.value
        elif isinstance(node, ast.AnnAssign):
            target = node.target
            value = node.value
        else:
            continue
        if (
            isinstance(target, ast.Name)
            and value is not None
            and (
                before_position is None
                or (node.lineno, node.col_offset) < before_position
            )
        ):
            assignments[target.id] = value
    return assignments


def _simple_module_assignments(
    module: _ModuleRecord,
) -> dict[str, ast.AST]:
    assignments: dict[str, ast.AST] = {}
    for statement in module.tree.body:
        if isinstance(statement, ast.Assign) and len(statement.targets) == 1:
            target = statement.targets[0]
            value = statement.value
        elif isinstance(statement, ast.AnnAssign):
            target = statement.target
            value = statement.value
        else:
            continue
        if isinstance(target, ast.Name) and value is not None:
            assignments[target.id] = value
    return assignments


def _resolve_local_node(
    node: ast.AST,
    *,
    assignments: Mapping[str, ast.AST],
    seen: frozenset[str] = frozenset(),
) -> ast.AST:
    if (
        not isinstance(node, ast.Name)
        or node.id not in assignments
        or node.id in seen
    ):
        return node
    return _resolve_local_node(
        assignments[node.id],
        assignments=assignments,
        seen=seen | {node.id},
    )


def _resolve_local_function(
    call: ast.Call,
    *,
    record: _FunctionRecord,
    module: _ModuleRecord,
    functions: Mapping[str, _FunctionRecord],
) -> str | None:
    local_bindings = _function_local_bindings(record.node)
    resolved_function = _resolve_local_node(
        call.func,
        assignments=_simple_local_assignments(
            record,
            before=call,
        ),
    )
    if (
        isinstance(resolved_function, ast.Name)
        and resolved_function.id not in local_bindings
    ):
        resolved_function = _resolve_local_node(
            resolved_function,
            assignments=_simple_module_assignments(module),
        )
    callee = _expression_name(resolved_function)
    if isinstance(resolved_function, ast.Name):
        local = f"{record.module}:{resolved_function.id}"
        if local in functions:
            return local
        imported = module.imports.get(resolved_function.id)
        if imported is not None:
            candidate = imported.rsplit(".", 1)
            if len(candidate) == 2:
                identifier = f"{candidate[0]}:{candidate[1]}"
                if identifier in functions:
                    return identifier
    if (
        isinstance(resolved_function, ast.Attribute)
        and isinstance(resolved_function.value, ast.Name)
        and resolved_function.value.id in {"self", "cls"}
        and record.class_name is not None
    ):
        candidate = (
            f"{record.module}:{record.class_name}."
            f"{resolved_function.attr}"
        )
        if candidate in functions:
            return candidate
    if "." in callee:
        first, suffix = callee.split(".", 1)
        imported = module.imports.get(first)
        if imported is not None:
            candidate = f"{imported}:{suffix}"
            if candidate in functions:
                return candidate
    return None


def _reachable_functions(
    root: str,
    *,
    modules: Mapping[str, _ModuleRecord],
    functions: Mapping[str, _FunctionRecord],
) -> tuple[_FunctionRecord, ...]:
    pending: deque[str] = deque((root,))
    visited: set[str] = set()
    reachable: list[_FunctionRecord] = []
    while pending:
        identifier = pending.popleft()
        if identifier in visited:
            continue
        visited.add(identifier)
        record = functions.get(identifier)
        if record is None:
            continue
        reachable.append(record)
        module = modules[record.module]
        for node in _function_nodes(record):
            if not isinstance(node, ast.Call):
                continue
            target = _resolve_local_function(
                node,
                record=record,
                module=module,
                functions=functions,
            )
            if target is not None and target not in visited:
                pending.append(target)
    return tuple(reachable)


def _processor_class_names(
    manifest: ArchitectureManifest,
) -> frozenset[str]:
    return frozenset(
        root.split(":", 1)[1].split(".", 1)[0]
        for root in manifest.processor_roots
    )


def _check_processor_reachability(
    modules: Mapping[str, _ModuleRecord],
    manifest: ArchitectureManifest,
    violations: list[ArchitectureViolation],
) -> None:
    functions = _function_index(modules)
    processor_classes = _processor_class_names(manifest)
    for root in manifest.processor_roots:
        root_record = functions.get(root)
        if root_record is None:
            module = modules.get(root.split(":", 1)[0])
            _add(
                violations,
                rule="MISSING_PROCESSOR_ROOT",
                module=module,
                line=1,
                detail=root,
            )
            continue
        own_class = root_record.class_name
        for record in _reachable_functions(
            root,
            modules=modules,
            functions=functions,
        ):
            for node in _function_nodes(record):
                if not isinstance(node, ast.Call):
                    continue
                if (
                    isinstance(node.func, ast.Attribute)
                    and node.func.attr == "execute"
                ):
                    _add(
                        violations,
                        rule="PROCESSOR_TO_PROCESSOR_REACHABILITY",
                        module=modules[record.module],
                        line=node.lineno,
                        detail=(
                            f"{root} reaches {record.qualname} -> "
                            f"{_expression_name(node.func)}"
                        ),
                    )
                    continue
                called = _expression_name(node.func).rsplit(".", 1)[-1]
                if (
                    called in processor_classes
                    and called != own_class
                ):
                    _add(
                        violations,
                        rule="PROCESSOR_TO_PROCESSOR_REACHABILITY",
                        module=modules[record.module],
                        line=node.lineno,
                        detail=(
                            f"{root} reaches {record.qualname} -> {called}"
                        ),
                    )


def _check_processor_contracts(
    modules: Mapping[str, _ModuleRecord],
    manifest: ArchitectureManifest,
    violations: list[ArchitectureViolation],
) -> None:
    classes = _class_index(modules)
    input_contracts = tuple(
        (module, node)
        for identifier, (module, node) in classes.items()
        if identifier.endswith(":ProcessorExecutionInput")
    )
    if len(input_contracts) != 1:
        _add(
            violations,
            rule="PROCESSOR_EXECUTION_INPUT_SCHEMA",
            module=input_contracts[0][0] if input_contracts else None,
            line=input_contracts[0][1].lineno if input_contracts else 1,
            detail=(
                "expected exactly one ProcessorExecutionInput; "
                f"observed {len(input_contracts)}"
            ),
        )
    else:
        module, node = input_contracts[0]
        observed = _class_fields(node)
        if observed != _PROCESSOR_INPUT_FIELDS:
            _add(
                violations,
                rule="PROCESSOR_EXECUTION_INPUT_SCHEMA",
                module=module,
                line=node.lineno,
                detail=(
                    f"ProcessorExecutionInput fields are "
                    f"{sorted(observed)}; expected "
                    f"{sorted(_PROCESSOR_INPUT_FIELDS)}"
                ),
            )

    processor_classes = _processor_class_names(manifest)
    for root in manifest.processor_roots:
        function = _function_index(modules).get(root)
        if function is not None:
            positional = (
                *function.node.args.posonlyargs,
                *function.node.args.args,
            )
            parameters = tuple(
                argument.arg
                for argument in positional
                if argument.arg not in {"self", "cls"}
            )
            keyword_only = tuple(
                argument.arg
                for argument in function.node.args.kwonlyargs
            )
            if (
                parameters != ("execution_input",)
                or keyword_only
                or function.node.args.vararg is not None
                or function.node.args.kwarg is not None
            ):
                _add(
                    violations,
                    rule="PROCESSOR_EXECUTE_SIGNATURE",
                    module=modules[function.module],
                    line=function.node.lineno,
                    detail=(
                        f"{function.qualname} parameters are "
                        f"{parameters + keyword_only}; expected "
                        "only execution_input"
                    ),
                )
        module_name, qualname = root.split(":", 1)
        class_name = qualname.split(".", 1)[0]
        located = classes.get(f"{module_name}:{class_name}")
        if located is None:
            continue
        module, class_node = located
        for statement in class_node.body:
            if not (
                isinstance(
                    statement,
                    (ast.FunctionDef, ast.AsyncFunctionDef),
                )
                and statement.name == "__init__"
            ):
                continue
            arguments = (
                *statement.args.posonlyargs,
                *statement.args.args,
                *statement.args.kwonlyargs,
            )
            for argument in arguments:
                if argument.arg in {"self", "cls"}:
                    continue
                tokens = _identifier_tokens(argument.arg)
                annotation = (
                    _resolve_module_alias(
                        module,
                        _expression_name(argument.annotation),
                    )
                    if argument.annotation is not None
                    else ""
                )
                annotation_lower = annotation.lower()
                if (
                    tokens & _FORBIDDEN_PRE_ROUTING_DEPENDENCY_TOKENS
                    or "ImageBundleService" in annotation
                    or any(
                        marker in annotation_lower
                        for marker in (
                            "authorization",
                            "authorizer",
                            "bundle",
                            "credential",
                        )
                    )
                ):
                    _add(
                        violations,
                        rule="PROCESSOR_PRE_ROUTING_DEPENDENCY",
                        module=module,
                        line=argument.lineno,
                        detail=(
                            f"{class_name} constructor accepts "
                            f"{argument.arg}: {annotation or '<untyped>'}"
                        ),
                    )
                if not (
                    tokens & _FORBIDDEN_PROCESSOR_DEPENDENCY_TOKENS
                    or any(
                        processor in annotation
                        for processor in processor_classes
                    )
                    or "ExecutionResult" in annotation
                ):
                    continue
                _add(
                    violations,
                    rule="PROCESSOR_DEPENDENCY",
                    module=module,
                    line=argument.lineno,
                    detail=(
                        f"{class_name} constructor accepts "
                        f"{argument.arg}: {annotation or '<untyped>'}"
                    ),
                )

        for node in ast.walk(module.tree):
            if not isinstance(node, (ast.Import, ast.ImportFrom)):
                continue
            for imported in _import_targets(module, node):
                symbol = imported.rsplit(".", 1)[-1]
                if not (
                    "StateStore" in symbol
                    or symbol == "ConversationStatePort"
                    or "conversation_state" in imported.lower()
                ):
                    continue
                _add(
                    violations,
                    rule="PROCESSOR_STATE_STORE_IMPORT",
                    module=module,
                    line=node.lineno,
                    detail=(
                        f"{class_name} module imports state store "
                        f"{imported}"
                    ),
                )


def _resolved_processor_entry_calls(
    module: _ModuleRecord,
    function: _FunctionRecord,
) -> tuple[ast.Call, ...]:
    trusted_imports = _trusted_module_imports(module)
    local_bindings = _function_local_bindings(function.node)
    matches: list[ast.Call] = []
    for call in _executable_call_nodes(function.node):
        callee = _expression_name(call.func)
        resolved = None
        if isinstance(call.func, ast.Name):
            if call.func.id not in local_bindings:
                resolved = trusted_imports.get(call.func.id)
        elif isinstance(call.func, ast.Attribute):
            first = callee.split(".", 1)[0]
            if (
                first in trusted_imports
                and first not in local_bindings
            ):
                resolved = _resolve_module_alias(module, callee)
        if resolved == _PROCESSOR_ENTRY_OBSERVER:
            matches.append(call)
    return tuple(matches)


def _valid_processor_entry_call(call: ast.Call) -> bool:
    keywords = {
        keyword.arg: keyword.value
        for keyword in call.keywords
        if keyword.arg is not None
    }
    return (
        len(call.args) == 1
        and len(keywords) == 3
        and isinstance(keywords.get("execution_input"), ast.Name)
        and keywords["execution_input"].id == "execution_input"
        and isinstance(keywords.get("processor_instance"), ast.Name)
        and keywords["processor_instance"].id == "self"
        and ast.unparse(keywords.get("implementation"))
        == "type(self).__qualname__"
    )


def _check_processor_entry_observation(
    modules: Mapping[str, _ModuleRecord],
    manifest: ArchitectureManifest,
    violations: list[ArchitectureViolation],
) -> None:
    functions = _function_index(modules)
    processor_roots = set(manifest.processor_roots)
    for identifier, function in functions.items():
        module = modules[function.module]
        calls = _resolved_processor_entry_calls(module, function)
        if not calls:
            continue
        if identifier not in processor_roots:
            for call in calls:
                _add(
                    violations,
                    rule="PROCESSOR_CONCRETE_ENTRY_OBSERVATION",
                    module=module,
                    line=call.lineno,
                    detail=(
                        f"{function.qualname} claims a concrete "
                        "processor entry outside a processor execute root"
                    ),
                )

    for root in manifest.processor_roots:
        function = functions.get(root)
        if function is None:
            continue
        module = modules[function.module]
        calls = _resolved_processor_entry_calls(module, function)
        direct_calls = tuple(
            statement.value
            for statement in function.node.body
            if isinstance(statement, ast.Expr)
            and isinstance(statement.value, ast.Call)
            and statement.value in calls
        )
        if (
            len(calls) == 1
            and len(direct_calls) == 1
            and _valid_processor_entry_call(calls[0])
        ):
            continue
        _add(
            violations,
            rule="PROCESSOR_CONCRETE_ENTRY_OBSERVATION",
            module=module,
            line=function.node.lineno,
            detail=(
                f"{function.qualname} must make exactly one direct "
                "notify_processor_entry call with the concrete instance"
            ),
        )


def _check_processor_call_signatures(
    modules: Mapping[str, _ModuleRecord],
    violations: list[ArchitectureViolation],
) -> None:
    for module in modules.values():
        for function in module.functions.values():
            for node in _function_nodes(function):
                if not (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "execute"
                ):
                    continue
                assignments = _simple_local_assignments(
                    function,
                    before=node,
                )
                receiver = _resolve_local_node(
                    node.func.value,
                    assignments=assignments,
                )
                if not isinstance(receiver, ast.Subscript):
                    continue
                registry = _expression_name(receiver.value)
                if not registry.endswith("processor_registry"):
                    continue
                selector_node = _resolve_local_node(
                    receiver.slice,
                    assignments=assignments,
                )
                selector = (
                    _expression_name(selector_node)
                    or (
                        str(selector_node.value)
                        if isinstance(selector_node, ast.Constant)
                        else ""
                    )
                )
                valid_argument = (
                    selector.endswith("decision.processor")
                    and len(node.args) == 1
                    and isinstance(node.args[0], ast.Name)
                    and node.args[0].id == "execution_input"
                    and not node.keywords
                )
                if valid_argument:
                    continue
                _add(
                    violations,
                    rule="PROCESSOR_CALL_SIGNATURE",
                    module=module,
                    line=node.lineno,
                    detail=(
                        f"{function.qualname} must call the selected "
                        "processor with exactly execution_input; "
                        f"observed selector {selector or '<unknown>'}"
                    ),
                )


def _check_post_router_graph(
    modules: Mapping[str, _ModuleRecord],
    manifest: ArchitectureManifest,
    violations: list[ArchitectureViolation],
) -> None:
    functions = _function_index(modules)
    emitted: set[tuple[str, str, int, str]] = set()
    for root in manifest.post_router_roots:
        for record in _reachable_functions(
            root,
            modules=modules,
            functions=functions,
        ):
            module = modules[record.module]
            for node in _function_nodes(record):
                if isinstance(node, ast.Attribute):
                    field = node.attr
                    expression = _expression_name(node)
                    raw_message = (
                        field == "message"
                        and any(
                            part in {
                                "payload",
                                "request",
                                "turn",
                                "user_turn",
                            }
                            for part in expression.split(".")[:-1]
                        )
                    )
                    if (
                        field not in _RAW_TEXT_FIELDS
                        and not raw_message
                    ):
                        continue
                    key = (
                        "POST_ROUTER_RAW_TEXT_ACCESS",
                        module.file,
                        node.lineno,
                        field,
                    )
                    if key in emitted:
                        continue
                    emitted.add(key)
                    _add(
                        violations,
                        rule=key[0],
                        module=module,
                        line=node.lineno,
                        detail=(
                            f"{root} reaches raw field {field} "
                            f"through {record.qualname}"
                        ),
                    )
                elif isinstance(node, ast.Call):
                    expression = _resolve_module_alias(
                        module,
                        _expression_name(node.func),
                    )
                    callee = expression.rsplit(".", 1)[-1]
                    receiver = (
                        expression.rsplit(".", 1)[0]
                        if "." in expression
                        else ""
                    )
                    task_copy = (
                        callee == "model_copy"
                        and receiver.rsplit(".", 1)[-1]
                        in {"task", "task_plan", "effective_task"}
                    )
                    task_constructor = callee == "TaskPlan"
                    if task_copy or task_constructor:
                        key = (
                            "POST_ROUTER_TASK_MUTATION",
                            module.file,
                            node.lineno,
                            callee,
                        )
                        if key not in emitted:
                            emitted.add(key)
                            _add(
                                violations,
                                rule=key[0],
                                module=module,
                                line=node.lineno,
                                detail=(
                                    f"{root} mutates executable task via "
                                    f"{callee} through {record.qualname}"
                                ),
                            )
                    if callee not in _SEMANTIC_PARSERS:
                        continue
                    key = (
                        "POST_ROUTER_SEMANTIC_PARSER",
                        module.file,
                        node.lineno,
                        callee,
                    )
                    if key in emitted:
                        continue
                    emitted.add(key)
                    _add(
                        violations,
                        rule=key[0],
                        module=module,
                        line=node.lineno,
                        detail=(
                            f"{root} reaches semantic parser {callee} "
                            f"through {record.qualname}"
                        ),
                    )


def _check_post_router_data_contracts(
    modules: Mapping[str, _ModuleRecord],
    violations: list[ArchitectureViolation],
) -> None:
    module = modules.get(
        "app.guide.retrieval.product_evidence_retrieval"
    )
    if module is not None:
        expected_contracts = {
            "EvidenceQuery": _EVIDENCE_QUERY_FIELDS,
            "PreparedEvidenceSearch": _PREPARED_EVIDENCE_SEARCH_FIELDS,
        }
        for class_name, expected_fields in expected_contracts.items():
            node = module.classes.get(class_name)
            if node is None:
                _add(
                    violations,
                    rule="POST_ROUTER_RAW_TEXT_ACCESS",
                    module=module,
                    line=1,
                    detail=f"missing structured {class_name} contract",
                )
                continue
            observed_fields = _class_fields(node)
            if observed_fields == expected_fields:
                continue
            _add(
                violations,
                rule="POST_ROUTER_RAW_TEXT_ACCESS",
                module=module,
                line=node.lineno,
                detail=(
                    f"{class_name} fields are {sorted(observed_fields)}; "
                    f"expected {sorted(expected_fields)}"
                ),
            )
    execution_module = modules.get(
        "app.guide.application.execution_contracts"
    )
    if execution_module is None:
        return
    image_evidence = execution_module.classes.get(
        "ImageRoutingEvidence"
    )
    if image_evidence is None:
        return
    observed_fields = _class_fields(image_evidence)
    if observed_fields == _IMAGE_ROUTING_EVIDENCE_FIELDS:
        return
    _add(
        violations,
        rule="POST_ROUTER_PRE_ROUTING_AUTHORITY",
        module=execution_module,
        line=image_evidence.lineno,
        detail=(
            "ImageRoutingEvidence fields are "
            f"{sorted(observed_fields)}; expected "
            f"{sorted(_IMAGE_ROUTING_EVIDENCE_FIELDS)}"
        ),
    )


def _check_knowledge_retrieval_boundaries(
    modules: Mapping[str, _ModuleRecord],
    violations: list[ArchitectureViolation],
) -> None:
    general_module = modules.get(
        "app.guide.retrieval.general_knowledge_retrieval"
    )
    if general_module is not None:
        for imported in sorted(set(general_module.imports.values())):
            if "product_evidence" not in imported:
                continue
            _add(
                violations,
                rule="KNOWLEDGE_RETRIEVER_BOUNDARY",
                module=general_module,
                line=1,
                detail=(
                    "general knowledge imports product_evidence: "
                    f"{imported}"
                ),
            )

    product_module = modules.get(
        "app.guide.retrieval.product_evidence_retrieval"
    )
    if product_module is not None:
        for imported in sorted(set(product_module.imports.values())):
            if not any(
                token in imported.casefold()
                for token in ("embedding", "vector")
            ):
                continue
            _add(
                violations,
                rule="PRODUCT_EVIDENCE_TEXT_VECTOR",
                module=product_module,
                line=1,
                detail=(
                    "product evidence imports text embedding/vector "
                    f"dependency: {imported}"
                ),
            )
        for node in ast.walk(product_module.tree):
            if (
                not isinstance(node, ast.Constant)
                or not isinstance(node.value, str)
            ):
                continue
            source_name = next(
                (
                    value
                    for value in (
                        "seed_dump.sql",
                        "beauty_products_seed.json",
                        "qa_facts",
                    )
                    if value in node.value
                ),
                None,
            )
            if source_name is None:
                continue
            _add(
                violations,
                rule="PRODUCT_EVIDENCE_RAW_QA_SOURCE",
                module=product_module,
                line=node.lineno,
                detail=(
                    "product evidence runtime reads raw FAQ source "
                    f"{source_name}"
                ),
            )

    for class_name in (
        "ProductEvidenceRetriever",
        "GeneralKnowledgeRetriever",
    ):
        owners = tuple(
            module
            for module in modules.values()
            if class_name in module.classes
        )
        if len(owners) <= 1:
            continue
        for module in owners[1:]:
            _add(
                violations,
                rule="KNOWLEDGE_RETRIEVER_DUPLICATE",
                module=module,
                line=module.classes[class_name].lineno,
                detail=f"duplicate {class_name}",
            )


def _check_processor_collector_separation(
    modules: Mapping[str, _ModuleRecord],
    violations: list[ArchitectureViolation],
) -> None:
    for module in modules.values():
        for class_name, class_node in module.classes.items():
            methods = {
                statement.name
                for statement in class_node.body
                if isinstance(
                    statement,
                    (ast.FunctionDef, ast.AsyncFunctionDef),
                )
            }
            if {
                "execute",
                "prepare_routing_evidence",
            } <= methods:
                _add(
                    violations,
                    rule="PROCESSOR_COLLECTOR_ROLE_ALIAS",
                    module=module,
                    line=class_node.lineno,
                    detail=(
                        f"{class_name} exposes both processor execute and "
                        "pre-routing evidence collection"
                    ),
                )
            if "execute" not in methods:
                continue
            for method_name in sorted(
                methods
                & _FORBIDDEN_PROCESSOR_PRODUCT_RESOLUTION_METHODS
            ):
                method = next(
                    statement
                    for statement in class_node.body
                    if isinstance(
                        statement,
                        (ast.FunctionDef, ast.AsyncFunctionDef),
                    )
                    and statement.name == method_name
                )
                _add(
                    violations,
                    rule="PROCESSOR_PRE_ROUTING_PRODUCT_RESOLUTION",
                    module=module,
                    line=method.lineno,
                    detail=(
                        f"{class_name} exposes pre-routing capability "
                        f"{method_name}"
                    ),
                )
            initializer = next(
                (
                    statement
                    for statement in class_node.body
                    if isinstance(
                        statement,
                        (ast.FunctionDef, ast.AsyncFunctionDef),
                    )
                    and statement.name == "__init__"
                ),
                None,
            )
            if initializer is None:
                continue
            arguments = (
                *initializer.args.posonlyargs,
                *initializer.args.args,
                *initializer.args.kwonlyargs,
            )
            for argument in arguments:
                annotation = (
                    _resolve_module_alias(
                        module,
                        _expression_name(argument.annotation),
                    )
                    if argument.annotation is not None
                    else ""
                )
                if (
                    argument.arg == "product_name_resolver"
                    or annotation.rsplit(".", 1)[-1]
                    == "ProductNameResolver"
                ):
                    _add(
                        violations,
                        rule=(
                            "PROCESSOR_PRE_ROUTING_PRODUCT_RESOLUTION"
                        ),
                        module=module,
                        line=argument.lineno,
                        detail=(
                            f"{class_name} constructor accepts "
                            f"{argument.arg}: "
                            f"{annotation or '<untyped>'}"
                        ),
                    )
        for node in ast.walk(module.tree):
            if isinstance(node, ast.Call):
                keywords = {
                    keyword.arg: keyword.value
                    for keyword in node.keywords
                    if keyword.arg is not None
                }
                processor = keywords.get("image_processor")
                collector = keywords.get("image_evidence_collector")
                if (
                    processor is not None
                    and collector is not None
                    and ast.dump(processor) == ast.dump(collector)
                ):
                    _add(
                        violations,
                        rule="PROCESSOR_COLLECTOR_ROLE_ALIAS",
                        module=module,
                        line=node.lineno,
                        detail=(
                            "image_processor and image_evidence_collector "
                            f"share {_expression_name(processor)}"
                        ),
                    )
                continue
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            value = node.value
            if value is None:
                continue
            targets = (
                node.targets
                if isinstance(node, ast.Assign)
                else (node.target,)
            )
            target_names = {
                name
                for target in targets
                for name in _target_names(target)
            }
            value_name = _expression_name(value).rsplit(".", 1)[-1]
            if (
                any("evidence_collector" in name for name in target_names)
                and value_name in {"processor", "image_processor"}
            ):
                _add(
                    violations,
                    rule="PROCESSOR_COLLECTOR_ROLE_ALIAS",
                    module=module,
                    line=node.lineno,
                    detail=(
                        f"{sorted(target_names)[0]} aliases {value_name}"
                    ),
                )
            elif (
                value_name == "image_processor"
                and "image_processor" not in target_names
            ):
                _add(
                    violations,
                    rule="PROCESSOR_COLLECTOR_ROLE_ALIAS",
                    module=module,
                    line=node.lineno,
                    detail=(
                        f"{sorted(target_names)[0]} aliases image_processor"
                    ),
                )


def _function_parameter_defaults(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> dict[str, ast.AST | None]:
    positional = (*node.args.posonlyargs, *node.args.args)
    positional_defaults = {
        argument.arg: default
        for argument, default in zip(
            positional[-len(node.args.defaults):],
            node.args.defaults,
            strict=True,
        )
    } if node.args.defaults else {}
    defaults: dict[str, ast.AST | None] = {
        argument.arg: positional_defaults.get(argument.arg)
        for argument in positional
    }
    defaults.update(
        {
            argument.arg: default
            for argument, default in zip(
                node.args.kwonlyargs,
                node.args.kw_defaults,
                strict=True,
            )
        }
    )
    return defaults


def _annotation_allows_none(node: ast.AST | None) -> bool:
    return node is not None and any(
        isinstance(item, ast.Constant) and item.value is None
        for item in ast.walk(node)
    )


def _check_presentation_responsibility(
    modules: Mapping[str, _ModuleRecord],
    violations: list[ArchitectureViolation],
) -> None:
    allowed_mapping_calls = {
        "app.guide.presentation.copywriter_contracts:"
        "PresentationPacket.validate_slots_and_sections",
        "app.guide.presentation.presentation_packet:"
        "build_presentation_packet",
    }
    for module in modules.values():
        for class_name, class_node in module.classes.items():
            if class_name.rsplit(".", 1)[-1] != "PresentationPacket":
                continue
            responsibility = next(
                (
                    statement
                    for statement in class_node.body
                    if (
                        isinstance(statement, ast.AnnAssign)
                        and "responsibility"
                        in _target_names(statement.target)
                    )
                ),
                None,
            )
            if (
                responsibility is not None
                and responsibility.value is None
                and not _annotation_allows_none(
                    responsibility.annotation
                )
            ):
                continue
            _add(
                violations,
                rule="PRESENTATION_RESPONSIBILITY_INFERENCE",
                module=module,
                line=(
                    responsibility.lineno
                    if responsibility is not None
                    else class_node.lineno
                ),
                detail=(
                    f"{class_name}.responsibility must be explicit "
                    "and non-optional"
                ),
            )
        for function in module.functions.values():
            if function.node.name == "build_presentation_packet":
                parameters = _function_parameter_defaults(function.node)
                if (
                    "responsibility" not in parameters
                    or parameters["responsibility"] is not None
                ):
                    _add(
                        violations,
                        rule="PRESENTATION_RESPONSIBILITY_INFERENCE",
                        module=module,
                        line=function.node.lineno,
                        detail=(
                            "build_presentation_packet responsibility "
                            "must be required"
                        ),
                    )
            for node in _function_nodes(function):
                if not isinstance(node, ast.Call):
                    continue
                callee = _expression_name(node.func).rsplit(".", 1)[-1]
                if (
                    callee == "build_presentation_packet"
                    and not any(
                        keyword.arg == "responsibility"
                        for keyword in node.keywords
                    )
                ):
                    _add(
                        violations,
                        rule="PRESENTATION_RESPONSIBILITY_INFERENCE",
                        module=module,
                        line=node.lineno,
                        detail=(
                            f"{function.qualname} omits responsibility"
                        ),
                    )
                if (
                    callee == "responsibility_for_presentation_mode"
                    and function.identifier not in allowed_mapping_calls
                ):
                    _add(
                        violations,
                        rule="PRESENTATION_RESPONSIBILITY_INFERENCE",
                        module=module,
                        line=node.lineno,
                        detail=(
                            f"{function.qualname} infers responsibility "
                            "from presentation mode"
                        ),
                    )


def _check_single_unified_flow_entrypoint(
    modules: Mapping[str, _ModuleRecord],
    violations: list[ArchitectureViolation],
) -> None:
    for module in modules.values():
        for class_name, class_node in module.classes.items():
            if class_name.rsplit(".", 1)[-1] != "UnifiedGuideFlow":
                continue
            for statement in class_node.body:
                if (
                    isinstance(
                        statement,
                        (ast.FunctionDef, ast.AsyncFunctionDef),
                    )
                    and statement.name == "stream_image"
                ):
                    _add(
                        violations,
                        rule="PARALLEL_UNIFIED_FLOW_ENTRYPOINT",
                        module=module,
                        line=statement.lineno,
                        detail=(
                            f"{class_name}.stream_image is a second "
                            "production orchestration entrypoint"
                        ),
                    )
        for call in module.calls:
            if (
                _expression_name(call.node.func).rsplit(".", 1)[-1]
                == "stream_image"
            ):
                _add(
                    violations,
                    rule="PARALLEL_UNIFIED_FLOW_ENTRYPOINT",
                    module=module,
                    line=call.line,
                    detail=f"{call.scope} calls stream_image",
                )


def _check_presentation_mode_authority(
    modules: Mapping[str, _ModuleRecord],
    violations: list[ArchitectureViolation],
) -> None:
    module = modules.get(
        "app.guide.presentation.presentation_compiler"
    )
    if module is None:
        return
    for call in module.calls:
        if (
            _resolve_module_alias(module, call.callee).rsplit(".", 1)[-1]
            != "decision_for_responsibility"
        ):
            continue
        _add(
            violations,
            rule="PRESENTATION_MODE_REDERIVATION",
            module=module,
            line=call.line,
            detail=(
                f"{call.scope} calls decision_for_responsibility "
                "after routing"
            ),
        )


def _check_production_encoder_overrides(
    modules: Mapping[str, _ModuleRecord],
    manifest: ArchitectureManifest,
    violations: list[ArchitectureViolation],
) -> None:
    composition_modules = {
        root.split(":", 1)[0] for root in manifest.composition_roots
    }
    for module_name in composition_modules:
        module = modules.get(module_name)
        if module is None:
            continue
        for function in module.functions.values():
            if (
                "." in function.qualname
                or function.node.name.startswith("_")
                or not function.node.name.startswith(
                    ("build_", "compose_")
                )
            ):
                continue
            parameters = (
                *function.node.args.posonlyargs,
                *function.node.args.args,
                *function.node.args.kwonlyargs,
            )
            for parameter in parameters:
                if "encoder" not in _identifier_tokens(parameter.arg):
                    continue
                _add(
                    violations,
                    rule="PRODUCTION_ENCODER_OVERRIDE",
                    module=module,
                    line=parameter.lineno,
                    detail=(
                        f"{function.qualname} exposes "
                        f"{parameter.arg}"
                    ),
                )


def _check_post_router_task_mutation(
    modules: Mapping[str, _ModuleRecord],
    violations: list[ArchitectureViolation],
) -> None:
    for module in modules.values():
        for function in module.functions.values():
            calls = tuple(
                node
                for node in _function_nodes(function)
                if isinstance(node, ast.Call)
            )
            route_lines = tuple(
                node.lineno
                for node in calls
                if _expression_name(node.func).rsplit(".", 1)[-1]
                in {"route_unified_turn", "_route"}
            )
            if not route_lines:
                continue
            first_route = min(route_lines)
            for node in calls:
                callee = _expression_name(node.func).rsplit(".", 1)[-1]
                if (
                    node.lineno <= first_route
                    or callee not in _POST_ROUTER_TASK_MUTATORS
                ):
                    continue
                _add(
                    violations,
                    rule="POST_ROUTER_TASK_MUTATION",
                    module=module,
                    line=node.lineno,
                    detail=(
                        f"{function.qualname} mutates executable task "
                        f"after routing via {callee}"
                    ),
                )


def _check_router_task_authority(
    modules: Mapping[str, _ModuleRecord],
    violations: list[ArchitectureViolation],
) -> None:
    for module in modules.values():
        for function in module.functions.values():
            if function.node.name != "route_unified_turn":
                continue
            task_plan_defaults = [
                default
                for argument, default in zip(
                    function.node.args.kwonlyargs,
                    function.node.args.kw_defaults,
                    strict=True,
                )
                if argument.arg == "task_plan"
            ]
            if task_plan_defaults != [None]:
                _add(
                    violations,
                    rule="ROUTER_TASK_AUTHORITY",
                    module=module,
                    line=function.node.lineno,
                    detail=(
                        "route_unified_turn must require task_plan "
                        "from the pre-routing owner"
                    ),
                )
            for node in _function_nodes(function):
                if (
                    isinstance(node, ast.Call)
                    and _expression_name(node.func).rsplit(".", 1)[-1]
                    == "plan_task"
                ):
                    _add(
                        violations,
                        rule="ROUTER_TASK_AUTHORITY",
                        module=module,
                        line=node.lineno,
                        detail=(
                            "route_unified_turn calls plan_task instead of "
                            "using pre-routing task_plan"
                        ),
                    )


def _module_matches(module: str, prefix: str) -> bool:
    return module == prefix or module.startswith(f"{prefix}.")


def _import_targets(
    module: _ModuleRecord,
    node: ast.Import | ast.ImportFrom,
) -> tuple[str, ...]:
    if isinstance(node, ast.Import):
        return tuple(item.name for item in node.names)
    base = _resolve_import_from(
        node,
        package=module.module.split(".")[:-1],
    )
    return tuple(
        ".".join(part for part in (base, item.name) if part)
        for item in node.names
        if item.name != "*"
    )


def _identifier_tokens(name: str) -> frozenset[str]:
    normalized = name.replace("-", "_").lower()
    return frozenset(token for token in normalized.split("_") if token)


def _check_adapter_boundaries(
    modules: Mapping[str, _ModuleRecord],
    manifest: ArchitectureManifest,
    violations: list[ArchitectureViolation],
) -> None:
    for module in modules.values():
        if not any(
            _module_matches(module.module, prefix)
            for prefix in manifest.adapter_packages
        ):
            continue
        parents = {
            child: parent
            for parent in ast.walk(module.tree)
            for child in ast.iter_child_nodes(parent)
        }
        for node in ast.walk(module.tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                for imported in _import_targets(module, node):
                    if not any(
                        _module_matches(imported, prefix)
                        for prefix in _BUSINESS_IMPORT_PREFIXES
                    ):
                        continue
                    _add(
                        violations,
                        rule="ADAPTER_BUSINESS_PROJECTION",
                        module=module,
                        line=node.lineno,
                        detail=(
                            f"{module.module} imports business owner "
                            f"{imported}"
                        ),
                    )
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                tokens = _identifier_tokens(node.name)
                if not (tokens & _SERIALIZATION_TOKENS):
                    continue
                _add(
                    violations,
                    rule="POST_CAS_SERIALIZATION_CAPABILITY",
                    module=module,
                    line=node.lineno,
                    detail=(
                        f"adapter retains serialization capability "
                        f"{node.name}"
                    ),
                )
            elif isinstance(node, ast.Call):
                callee = _expression_name(node.func)
                callee_name = callee.rsplit(".", 1)[-1]
                parent = parents.get(node)
                hashes_text_bytes = (
                    callee_name == "encode"
                    and isinstance(parent, ast.Call)
                    and node in parent.args
                    and _expression_name(parent.func).rsplit(".", 1)[-1]
                    == "sha256"
                )
                if hashes_text_bytes:
                    continue
                if (
                    callee_name
                    not in {
                        "dumps",
                        "model_dump",
                        "model_dump_json",
                    }
                    and not (
                        _identifier_tokens(callee_name)
                        & _SERIALIZATION_TOKENS
                    )
                ):
                    continue
                _add(
                    violations,
                    rule="POST_CAS_SERIALIZATION_CAPABILITY",
                    module=module,
                    line=node.lineno,
                    detail=f"adapter serializes through {callee}",
                )


def _referenced_names(node: ast.AST) -> frozenset[str]:
    return frozenset(
        (
            item.id
            if isinstance(item, ast.Name)
            else item.attr
        )
        for item in ast.walk(node)
        if isinstance(item, (ast.Name, ast.Attribute))
    )


def _check_registry_replacement(
    modules: Mapping[str, _ModuleRecord],
    violations: list[ArchitectureViolation],
) -> None:
    for module in modules.values():
        for function in module.functions.values():
            copied_registries: set[str] = set()
            for node in _function_nodes(function):
                if isinstance(node, ast.Call):
                    callee = _expression_name(node.func)
                    if callee.rsplit(".", 1)[-1] == "get_orchestrator":
                        _add(
                            violations,
                            rule=(
                                "SOURCE_DEPENDENT_PROCESSOR_REGISTRY"
                            ),
                            module=module,
                            line=node.lineno,
                            detail=(
                                f"{function.qualname} resolves a processor "
                                f"through {callee}"
                            ),
                        )
                        continue
                    if not (
                        isinstance(node.func, ast.Attribute)
                        and node.func.attr == "update"
                    ):
                        continue
                    receiver = _expression_name(node.func.value)
                    if (
                        receiver not in copied_registries
                        and "registry" not in receiver
                    ):
                        continue
                    _add(
                        violations,
                        rule="SOURCE_DEPENDENT_PROCESSOR_REGISTRY",
                        module=module,
                        line=node.lineno,
                        detail=(
                            f"{function.qualname} mutates dynamic registry "
                            f"{receiver}"
                        ),
                    )
                    continue
                if not isinstance(
                    node,
                    (ast.Assign, ast.AnnAssign),
                ):
                    continue
                value = node.value
                if value is None:
                    continue
                targets = (
                    node.targets
                    if isinstance(node, ast.Assign)
                    else (node.target,)
                )
                target_names = tuple(
                    name
                    for target in targets
                    for name in _target_names(target)
                )
                unpacked_registry = (
                    isinstance(value, ast.Dict)
                    and any(key is None for key in value.keys)
                    and any(
                        "registry" in name
                        for name in _referenced_names(value)
                    )
                )
                registry_union = (
                    isinstance(value, ast.BinOp)
                    and isinstance(value.op, ast.BitOr)
                    and any(
                        "registry" in name
                        for name in _referenced_names(value)
                    )
                )
                registry_copy = (
                    isinstance(value, ast.Call)
                    and isinstance(value.func, ast.Attribute)
                    and value.func.attr == "copy"
                    and "registry" in _expression_name(value.func.value)
                )
                if not (
                    unpacked_registry
                    or registry_union
                    or registry_copy
                ):
                    continue
                target = target_names[0] if target_names else "<unknown>"
                if registry_copy:
                    copied_registries.add(target)
                _add(
                    violations,
                    rule="SOURCE_DEPENDENT_PROCESSOR_REGISTRY",
                    module=module,
                    line=node.lineno,
                    detail=(
                        f"{function.qualname} constructs dynamic registry "
                        f"{target}"
                    ),
                )


def _call_uses_name(call: ast.Call, name: str) -> bool:
    return any(
        isinstance(node, ast.Name) and node.id == name
        for argument in (*call.args, *[item.value for item in call.keywords])
        for node in ast.walk(argument)
    )


def _check_result_rewrites(
    modules: Mapping[str, _ModuleRecord],
    violations: list[ArchitectureViolation],
) -> None:
    for module in modules.values():
        for function in module.functions.values():
            if function.node.name != "execute":
                continue
            core_results: dict[str, int] = {}
            for node in _function_nodes(function):
                if isinstance(node, (ast.Assign, ast.AnnAssign)):
                    value = node.value
                    if not isinstance(value, ast.Call):
                        continue
                    targets = (
                        node.targets
                        if isinstance(node, ast.Assign)
                        else (node.target,)
                    )
                    target_names = tuple(
                        name
                        for target in targets
                        for name in _target_names(target)
                    )
                    callee = _expression_name(value.func)
                    for target in target_names:
                        if (
                            target in core_results
                            and _call_uses_name(value, target)
                        ):
                            _add(
                                violations,
                                rule="POST_EXECUTION_RESULT_REWRITE",
                                module=module,
                                line=node.lineno,
                                detail=(
                                    f"{function.qualname} rewrites {target} "
                                    f"through {callee}"
                                ),
                            )
                        if callee.endswith("_execute_core"):
                            core_results[target] = node.lineno
                elif (
                    isinstance(node, ast.Return)
                    and isinstance(node.value, ast.Call)
                ):
                    callee = _expression_name(node.value.func)
                    for result_name in core_results:
                        if _call_uses_name(node.value, result_name):
                            _add(
                                violations,
                                rule="POST_EXECUTION_RESULT_REWRITE",
                                module=module,
                                line=node.lineno,
                                detail=(
                                    f"{function.qualname} wraps "
                                    f"{result_name} through {callee}"
                                ),
                            )


def _identity_value_is_synthetic(node: ast.AST) -> bool:
    names = {
        item.id.lower()
        for item in ast.walk(node)
        if isinstance(item, ast.Name)
    }
    names.update(
        item.attr.lower()
        for item in ast.walk(node)
        if isinstance(item, ast.Attribute)
    )
    return (
        any("session" in name for name in names)
        and any("version" in name for name in names)
    )


def _check_turn_identity(
    modules: Mapping[str, _ModuleRecord],
    violations: list[ArchitectureViolation],
) -> None:
    for module in modules.values():
        for node in ast.walk(module.tree):
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                value = node.value
                if value is None:
                    continue
                targets = (
                    node.targets
                    if isinstance(node, ast.Assign)
                    else (node.target,)
                )
                target_names = tuple(
                    name
                    for target in targets
                    for name in _target_names(target)
                )
                for target in target_names:
                    if (
                        target in {"request_id", "turn_id"}
                        and _identity_value_is_synthetic(value)
                    ):
                        _add(
                            violations,
                            rule="SYNTHETIC_TURN_IDENTITY",
                            module=module,
                            line=node.lineno,
                            detail=(
                                f"{target} is derived from session/version"
                            ),
                        )
            elif isinstance(node, ast.Call):
                for keyword in node.keywords:
                    if (
                        keyword.arg in {"request_id", "turn_id"}
                        and _identity_value_is_synthetic(keyword.value)
                    ):
                        _add(
                            violations,
                            rule="SYNTHETIC_TURN_IDENTITY",
                            module=module,
                            line=keyword.value.lineno,
                            detail=(
                                f"{keyword.arg} is derived from "
                                "session/version"
                            ),
                        )


def _check_test_seam_imports(
    modules: Mapping[str, _ModuleRecord],
    violations: list[ArchitectureViolation],
) -> None:
    for module in modules.values():
        for node in ast.walk(module.tree):
            if not isinstance(node, (ast.Import, ast.ImportFrom)):
                continue
            for imported in _import_targets(module, node):
                if not _module_matches(imported, "tests"):
                    continue
                _add(
                    violations,
                    rule="PRODUCTION_TEST_SEAM_IMPORT",
                    module=module,
                    line=node.lineno,
                    detail=(
                        f"{module.module} imports test seam {imported}"
                    ),
                )


def _check_post_cas_order(
    modules: Mapping[str, _ModuleRecord],
    manifest: ArchitectureManifest,
    violations: list[ArchitectureViolation],
) -> None:
    canonical = manifest.canonical_calls
    if "cas" not in canonical or "encoder" not in canonical:
        return
    cas_symbol = canonical["cas"][0]
    encoder_symbol = canonical["encoder"][0]
    for module in modules.values():
        by_scope: dict[str, list[_CallSite]] = {}
        for call in module.calls:
            by_scope.setdefault(call.scope, []).append(call)
        for scope, calls in by_scope.items():
            cas_lines = [
                call.line
                for call in calls
                if _callee_matches(call.callee, cas_symbol)
            ]
            encoder_calls = [
                call
                for call in calls
                if _callee_matches(call.callee, encoder_symbol)
            ]
            if not cas_lines:
                continue
            first_cas = min(cas_lines)
            for call in encoder_calls:
                if call.line <= first_cas:
                    continue
                _add(
                    violations,
                    rule="POST_CAS_SERIALIZATION_CAPABILITY",
                    module=module,
                    line=call.line,
                    detail=(
                        f"{scope} calls {encoder_symbol} after "
                        f"{cas_symbol}"
                    ),
                )


def _check_pre_routing_evidence_order(
    modules: Mapping[str, _ModuleRecord],
    violations: list[ArchitectureViolation],
) -> None:
    for module in modules.values():
        by_scope: dict[str, list[_CallSite]] = {}
        for call in module.calls:
            by_scope.setdefault(call.scope, []).append(call)
        for scope, calls in by_scope.items():
            evidence_calls = [
                call
                for call in calls
                if call.callee.rsplit(".", 1)[-1]
                == "prepare_routing_evidence"
            ]
            if not evidence_calls:
                continue
            compiler_lines = [
                call.line
                for call in calls
                if call.callee.rsplit(".", 1)[-1]
                in {"_compile", "compile_turn_meaning"}
            ]
            router_lines = [
                call.line
                for call in calls
                if call.callee.rsplit(".", 1)[-1]
                in {"_route", "route_unified_turn"}
            ]
            for call in evidence_calls:
                if (
                    len(compiler_lines) == 1
                    and len(router_lines) == 1
                    and compiler_lines[0] < call.line < router_lines[0]
                ):
                    continue
                _add(
                    violations,
                    rule="PRE_ROUTING_EVIDENCE_ORDER",
                    module=module,
                    line=call.line,
                    detail=(
                        f"{scope} calls prepare_routing_evidence "
                        "outside compile-to-router interval"
                    ),
                )


def _class_fields(node: ast.ClassDef) -> frozenset[str]:
    return frozenset(
        name
        for statement in node.body
        if isinstance(statement, ast.AnnAssign)
        for name in _target_names(statement.target)
    )


def _union_members(node: ast.AST) -> frozenset[str]:
    if isinstance(node, ast.Name):
        return frozenset((node.id,))
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return _union_members(node.left) | _union_members(node.right)
    if (
        isinstance(node, ast.Subscript)
        and _expression_name(node.value).rsplit(".", 1)[-1] == "Annotated"
    ):
        annotation = node.slice
        if isinstance(annotation, ast.Tuple) and annotation.elts:
            annotation = annotation.elts[0]
        return _union_members(annotation)
    return frozenset((_expression_name(node),))


def _check_snapshot_schema(
    modules: Mapping[str, _ModuleRecord],
    manifest: ArchitectureManifest,
    violations: list[ArchitectureViolation],
) -> None:
    classes = _class_index(modules)
    located = classes.get(manifest.snapshot_contract)
    if located is None:
        module = modules.get(manifest.snapshot_contract.split(":", 1)[0])
        _add(
            violations,
            rule="SNAPSHOT_TOP_LEVEL_SCHEMA",
            module=module,
            line=1,
            detail=f"missing {manifest.snapshot_contract}",
        )
        return
    module, snapshot = located
    observed = _class_fields(snapshot)
    if observed != _SNAPSHOT_FIELDS:
        _add(
            violations,
            rule="SNAPSHOT_TOP_LEVEL_SCHEMA",
            module=module,
            line=snapshot.lineno,
            detail=(
                f"ConversationSnapshot fields are {sorted(observed)}; "
                f"expected {sorted(_SNAPSHOT_FIELDS)}"
            ),
        )
    for class_name, expected in _NESTED_SLOT_FIELDS.items():
        entry = next(
            (
                (candidate_module, node)
                for identifier, (candidate_module, node) in classes.items()
                if identifier.endswith(f":{class_name}")
            ),
            None,
        )
        if entry is None:
            _add(
                violations,
                rule="SNAPSHOT_NESTED_SLOT_SCHEMA",
                module=module,
                line=snapshot.lineno,
                detail=f"missing {class_name}",
            )
            continue
        nested_module, nested = entry
        nested_fields = _class_fields(nested)
        if nested_fields == expected:
            continue
        _add(
            violations,
            rule="SNAPSHOT_NESTED_SLOT_SCHEMA",
            module=nested_module,
            line=nested.lineno,
            detail=(
                f"{class_name} fields are {sorted(nested_fields)}; "
                f"expected {sorted(expected)}"
            ),
        )
    for statement in module.tree.body:
        if not isinstance(statement, (ast.Assign, ast.AnnAssign)):
            continue
        targets = (
            statement.targets
            if isinstance(statement, ast.Assign)
            else (statement.target,)
        )
        if "ReplySlotState" not in {
            name for target in targets for name in _target_names(target)
        }:
            continue
        value = statement.value
        if value is None or _union_members(value) != _REPLY_SLOT_MEMBERS:
            _add(
                violations,
                rule="SNAPSHOT_NESTED_SLOT_SCHEMA",
                module=module,
                line=statement.lineno,
                detail="ReplySlotState has invalid members",
            )


def _check_request_contract(
    modules: Mapping[str, _ModuleRecord],
    manifest: ArchitectureManifest,
    violations: list[ArchitectureViolation],
) -> None:
    classes = _class_index(modules)
    located = classes.get(manifest.request_contract)
    if located is None:
        module = modules.get(manifest.request_contract.split(":", 1)[0])
        _add(
            violations,
            rule="MISSING_REQUEST_CONTRACT",
            module=module,
            line=1,
            detail=manifest.request_contract,
        )
        return
    module, request = located
    legacy = _class_fields(request) & _LEGACY_REQUEST_FIELDS
    for field in sorted(legacy):
        _add(
            violations,
            rule="LEGACY_REQUEST_FIELD",
            module=module,
            line=request.lineno,
            detail=f"{request.name} exposes {field}",
        )


def _check_legacy_public_capabilities(
    modules: Mapping[str, _ModuleRecord],
    violations: list[ArchitectureViolation],
) -> None:
    for module in modules.values():
        definitions = (
            *(name.rsplit(".", 1)[-1] for name in module.classes),
            *(name.rsplit(".", 1)[-1] for name in module.functions),
        )
        for symbol in sorted(
            _LEGACY_PUBLIC_CAPABILITIES.intersection(definitions)
        ):
            node = next(
                (
                    candidate
                    for name, candidate in module.classes.items()
                    if name.rsplit(".", 1)[-1] == symbol
                ),
                None,
            )
            if node is None:
                function = next(
                    record
                    for name, record in module.functions.items()
                    if name.rsplit(".", 1)[-1] == symbol
                )
                line = function.node.lineno
            else:
                line = node.lineno
            _add(
                violations,
                rule="LEGACY_PUBLIC_COLLECTOR",
                module=module,
                line=line,
                detail=f"legacy public capability {symbol} remains",
            )


def _check_dormant_compatibility_capabilities(
    modules: Mapping[str, _ModuleRecord],
    violations: list[ArchitectureViolation],
) -> None:
    for module in modules.values():
        for function in module.functions.values():
            symbol = function.qualname.rsplit(".", 1)[-1]
            if symbol not in _DORMANT_COMPATIBILITY_CAPABILITIES:
                continue
            _add(
                violations,
                rule="DORMANT_COMPATIBILITY_CAPABILITY",
                module=module,
                line=function.node.lineno,
                detail=f"dormant compatibility capability {symbol} remains",
            )


def _check_forbidden_legacy_modules(
    root: Path,
    violations: list[ArchitectureViolation],
) -> None:
    for relative_path in sorted(_FORBIDDEN_LEGACY_MODULE_PATHS):
        path = root / relative_path
        if not path.exists() and not path.is_symlink():
            continue
        violations.append(
            ArchitectureViolation(
                rule="FORBIDDEN_LEGACY_MODULE",
                file=relative_path,
                line=1,
                detail=f"forbidden legacy module remains: {relative_path}",
            )
        )


def _check_runtime_registration_owner(
    root: Path,
    violations: list[ArchitectureViolation],
) -> tuple[str, ...]:
    writer_path = root / "tools/guide_gates/attempt_ledger.py"
    if not writer_path.is_file() or writer_path.is_symlink():
        return ()
    tool_root = root / "tools/guide_gates"
    inspected: list[str] = []
    calls: list[tuple[str, str, int]] = []
    for path in sorted(tool_root.rglob("*.py")):
        if path.is_symlink() or "__pycache__" in path.parts:
            continue
        relative = path.relative_to(root).as_posix()
        inspected.append(_module_name(path.relative_to(root)))
        try:
            tree = ast.parse(
                path.read_text(encoding="utf-8"),
                filename=relative,
            )
        except (OSError, UnicodeError, SyntaxError):
            continue
        direct_aliases: set[str] = set()
        module_aliases: set[str] = set()
        for statement in tree.body:
            if (
                isinstance(statement, ast.ImportFrom)
                and statement.module == _RUNTIME_REGISTRATION_WRITER[0]
            ):
                direct_aliases.update(
                    alias.asname or alias.name
                    for alias in statement.names
                    if alias.name == _RUNTIME_REGISTRATION_WRITER[1]
                )
            elif isinstance(statement, ast.Import):
                module_aliases.update(
                    alias.asname or alias.name.split(".")[0]
                    for alias in statement.names
                    if alias.name == _RUNTIME_REGISTRATION_WRITER[0]
                )
        for function in (
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        ):
            for call in _executable_call_nodes(function):
                direct = (
                    isinstance(call.func, ast.Name)
                    and call.func.id in direct_aliases
                )
                qualified = (
                    isinstance(call.func, ast.Attribute)
                    and call.func.attr
                    == _RUNTIME_REGISTRATION_WRITER[1]
                    and isinstance(call.func.value, ast.Name)
                    and call.func.value.id in module_aliases
                )
                if direct or qualified:
                    calls.append((relative, function.name, call.lineno))
    expected_path, expected_function = _RUNTIME_REGISTRATION_OWNER
    if len(calls) != 1:
        violations.append(
            ArchitectureViolation(
                rule="NONCANONICAL_RUNTIME_REGISTRATION",
                file=(calls[0][0] if calls else expected_path),
                line=(calls[0][2] if calls else 1),
                detail=(
                    "runtime registration writer expected exactly one "
                    f"launcher call; observed {len(calls)}"
                ),
            )
        )
    for relative, function, line in calls:
        if (
            relative == expected_path
            and function == expected_function
        ):
            continue
        violations.append(
            ArchitectureViolation(
                rule="NONCANONICAL_RUNTIME_REGISTRATION",
                file=relative,
                line=line,
                detail=(
                    "runtime registration writer is owned by "
                    f"{expected_path}:{expected_function}; "
                    f"observed {relative}:{function}"
                ),
            )
        )
    return tuple(inspected)


def check_single_path_architecture(
    repo_root: str | Path,
    *,
    manifest: ArchitectureManifest,
) -> ArchitectureReport:
    root = Path(repo_root).resolve(strict=True)
    modules, violations = _load_modules(root)
    tool_modules = _check_runtime_registration_owner(root, violations)
    _check_forbidden_legacy_modules(root, violations)
    _check_roots(modules, manifest, violations)
    _check_public_static_mounts(modules, violations)
    _check_canonical_calls(modules, manifest, violations)
    _check_processor_contracts(modules, manifest, violations)
    _check_processor_entry_observation(
        modules,
        manifest,
        violations,
    )
    _check_processor_reachability(modules, manifest, violations)
    _check_processor_call_signatures(modules, violations)
    _check_post_router_graph(modules, manifest, violations)
    _check_post_router_data_contracts(modules, violations)
    _check_knowledge_retrieval_boundaries(modules, violations)
    _check_processor_collector_separation(modules, violations)
    _check_presentation_responsibility(modules, violations)
    _check_single_unified_flow_entrypoint(modules, violations)
    _check_presentation_mode_authority(modules, violations)
    _check_production_encoder_overrides(
        modules,
        manifest,
        violations,
    )
    _check_router_task_authority(modules, violations)
    _check_post_router_task_mutation(modules, violations)
    _check_adapter_boundaries(modules, manifest, violations)
    _check_registry_replacement(modules, violations)
    _check_result_rewrites(modules, violations)
    _check_turn_identity(modules, violations)
    _check_test_seam_imports(modules, violations)
    _check_pre_routing_evidence_order(modules, violations)
    _check_post_cas_order(modules, manifest, violations)
    _check_snapshot_schema(modules, manifest, violations)
    _check_request_contract(modules, manifest, violations)
    _check_legacy_public_capabilities(modules, violations)
    _check_dormant_compatibility_capabilities(modules, violations)
    unique = {
        (
            violation.rule,
            violation.file,
            violation.line,
            violation.detail,
        ): violation
        for violation in violations
    }
    ordered = tuple(
        unique[key]
        for key in sorted(
            unique,
            key=lambda item: (item[1], item[2], item[0], item[3]),
        )
    )
    return ArchitectureReport(
        inspected_modules=tuple(sorted({*modules, *tool_modules})),
        violations=ordered,
    )


def default_manifest() -> ArchitectureManifest:
    flow = "app.guide.application.unified_guide_flow:UnifiedGuideFlow"
    processors = (
        "app.guide.application.text_recommendation_flow:"
        "TextRecommendationOrchestrator.execute",
        "app.guide.application.image_recommendation_flow:"
        "ImageRecommendationOrchestrator.execute",
        "app.guide.application.consultation_chat_flow:"
        "ConsultationChatFlow.execute",
    )
    return ArchitectureManifest(
        production_roots=(
            "app.guide_runtime.app:create_app.chat_stream",
        ),
        composition_roots=(
            "app.guide_runtime.composition:"
            "build_consultation_vertical_runtime",
        ),
        canonical_calls={
            "compiler": (
                "compile_turn_meaning",
                f"{flow}._compile",
            ),
            "router": (
                "route_unified_turn",
                f"{flow}._route",
            ),
            "reducer": (
                "reduce_conversation_state",
                f"{flow}._commit_execution_result",
            ),
            "cas": (
                "_conversation_state.save",
                f"{flow}._commit_execution_result",
            ),
            "encoder": (
                "materialize_execution_envelope",
                f"{flow}._commit_execution_result",
            ),
        },
        processor_roots=processors,
        post_router_roots=processors,
        adapter_packages=(
            "app.guide.application.chat_api_adapter",
            "app.guide_runtime.sse",
        ),
        snapshot_contract=(
            "app.guide.feedback.contracts:ConversationSnapshot"
        ),
        request_contract=(
            "app.guide_runtime.contracts:ChatStreamRequest"
        ),
    )


def _write_report(path: Path, report: ArchitectureReport) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(
        report.to_payload(),
        ensure_ascii=True,
        indent=2,
        sort_keys=True,
    )
    try:
        with path.open("xb") as stream:
            stream.write(f"{serialized}\n".encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError:
        raise FileExistsError(
            f"architecture report already exists: {path}"
        ) from None
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        type=Path,
        required=True,
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    report = check_single_path_architecture(
        args.repo_root,
        manifest=default_manifest(),
    )
    _write_report(args.output, report)
    print(
        json.dumps(
            {
                "output": str(args.output),
                "passed": report.passed,
                "violation_count": len(report.violations),
            },
            ensure_ascii=True,
            sort_keys=True,
        )
    )
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
