#!/usr/bin/env python3
"""Enforce the single Guide production path from HTTP to encoded SSE."""

from __future__ import annotations

import argparse
import ast
from collections import deque
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
import json
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
_SEMANTIC_PARSERS = frozenset(
    {
        "find_explicit_mentions",
        "parse_scenarios",
        "plan_code_owned_transitions",
        "plan_route_transition_operations",
        "resolve_product_knowledge_dimensions",
    }
)
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


def _callee_matches(callee: str, symbol: str) -> bool:
    return callee == symbol or callee.endswith(f".{symbol}")


def _check_canonical_calls(
    modules: Mapping[str, _ModuleRecord],
    manifest: ArchitectureManifest,
    violations: list[ArchitectureViolation],
) -> None:
    all_calls = tuple(
        call for module in modules.values() for call in module.calls
    )
    for boundary, (symbol, owner) in manifest.canonical_calls.items():
        matches = tuple(
            call
            for call in all_calls
            if _callee_matches(call.callee, symbol)
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


def _resolve_local_function(
    call: ast.Call,
    *,
    record: _FunctionRecord,
    module: _ModuleRecord,
    functions: Mapping[str, _FunctionRecord],
) -> str | None:
    callee = _expression_name(call.func)
    if isinstance(call.func, ast.Name):
        local = f"{record.module}:{call.func.id}"
        if local in functions:
            return local
        imported = module.imports.get(call.func.id)
        if imported is not None:
            candidate = imported.rsplit(".", 1)
            if len(candidate) == 2:
                identifier = f"{candidate[0]}:{candidate[1]}"
                if identifier in functions:
                    return identifier
    if (
        isinstance(call.func, ast.Attribute)
        and isinstance(call.func.value, ast.Name)
        and call.func.value.id in {"self", "cls"}
        and record.class_name is not None
    ):
        candidate = (
            f"{record.module}:{record.class_name}.{call.func.attr}"
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
                    _expression_name(argument.annotation)
                    if argument.annotation is not None
                    else ""
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
                    and isinstance(node.func.value, ast.Subscript)
                ):
                    continue
                selector = _expression_name(node.func.value.slice)
                if not selector.endswith("decision.processor"):
                    continue
                valid_argument = (
                    len(node.args) == 1
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
                        "processor with exactly execution_input"
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
                    callee = _expression_name(node.func).rsplit(".", 1)[-1]
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


def check_single_path_architecture(
    repo_root: str | Path,
    *,
    manifest: ArchitectureManifest,
) -> ArchitectureReport:
    root = Path(repo_root).resolve(strict=True)
    modules, violations = _load_modules(root)
    _check_forbidden_legacy_modules(root, violations)
    _check_roots(modules, manifest, violations)
    _check_canonical_calls(modules, manifest, violations)
    _check_processor_contracts(modules, manifest, violations)
    _check_processor_reachability(modules, manifest, violations)
    _check_processor_call_signatures(modules, violations)
    _check_post_router_graph(modules, manifest, violations)
    _check_adapter_boundaries(modules, manifest, violations)
    _check_registry_replacement(modules, violations)
    _check_result_rewrites(modules, violations)
    _check_turn_identity(modules, violations)
    _check_test_seam_imports(modules, violations)
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
        inspected_modules=tuple(sorted(modules)),
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
    if path.exists():
        raise FileExistsError(f"architecture report already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    serialized = json.dumps(
        report.to_payload(),
        ensure_ascii=True,
        indent=2,
        sort_keys=True,
    )
    temporary.write_text(f"{serialized}\n", encoding="utf-8")
    temporary.replace(path)


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
