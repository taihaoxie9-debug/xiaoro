from __future__ import annotations

import ast
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[3]
PRODUCTION = (
    "app/guide/adapters/llm",
    "app/guide/understanding",
    "app/guide/intent",
    "app/guide/application",
    "app/guide/retrieval/product_evidence_retrieval.py",
    "app/static/chat.html",
    "app/static/guide-presentation.js",
)
_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")
_CJK = re.compile(r"[\u3400-\u9fff]")
_TEXT_NAMES = frozenset(
    {
        "content",
        "exact_text",
        "message",
        "output",
        "question_summary",
        "response",
        "source_text",
        "text",
    }
)
_PYTHON_TEXT_METHODS = frozenset(
    {
        "__contains__",
        "__eq__",
        "__ne__",
        "endswith",
        "find",
        "index",
        "startswith",
    }
)
_JAVASCRIPT_AST_GATE = r"""
const fs = require('node:fs');
const acorn = require('internal/deps/acorn/acorn/dist/acorn');
const walk = require('internal/deps/acorn/acorn-walk/dist/walk');

const source = fs.readFileSync(0, 'utf8');
const tree = acorn.parse(source, {
  allowAwaitOutsideFunction: true,
  ecmaVersion: 'latest',
  locations: true,
  sourceType: 'script',
});
const cjk = /[\u3400-\u9fff]/u;
const textNames = new Set([
  'content',
  'exactText',
  'exact_text',
  'message',
  'output',
  'questionSummary',
  'question_summary',
  'response',
  'sourceText',
  'source_text',
  'text',
]);
const textMethods = new Set([
  'endsWith',
  'includes',
  'indexOf',
  'localeCompare',
  'match',
  'matchAll',
  'replace',
  'replaceAll',
  'search',
  'startsWith',
]);
const regexMethods = new Set(['exec', 'test']);

function propertyName(node) {
  if (!node || node.type !== 'MemberExpression') return null;
  if (!node.computed && node.property.type === 'Identifier') {
    return node.property.name;
  }
  if (
    node.computed
    && node.property.type === 'Literal'
    && typeof node.property.value === 'string'
  ) {
    return node.property.value;
  }
  return null;
}

function containsCjk(node) {
  let found = false;
  if (!node) return false;
  walk.full(node, child => {
    if (
      child.type === 'Literal'
      && (
        (
          typeof child.value === 'string'
          && cjk.test(child.value)
        )
        || (
          child.regex
          && cjk.test(child.regex.pattern)
        )
      )
    ) {
      found = true;
    }
  });
  return found;
}

function objectHasCjkKey(node) {
  return Boolean(
    node
    && node.type === 'ObjectExpression'
    && node.properties.some(property => {
      const key = property.key;
      return (
        key
        && (
          (
            key.type === 'Literal'
            && typeof key.value === 'string'
            && cjk.test(key.value)
          )
          || (
            key.type === 'Identifier'
            && cjk.test(key.name)
          )
        )
      );
    })
  );
}

function containsRequestText(node) {
  let found = false;
  if (!node) return false;
  walk.full(node, child => {
    if (
      (
        child.type === 'Identifier'
        && textNames.has(child.name)
      )
      || (
        child.type === 'MemberExpression'
        && textNames.has(propertyName(child))
      )
    ) {
      found = true;
    }
  });
  return found;
}

const scopeByNode = new Map();
const parentScope = new Map();
const functionTypes = new Set([
  'FunctionDeclaration',
  'FunctionExpression',
  'ArrowFunctionExpression',
]);

walk.fullAncestor(tree, (node, ancestors) => {
  let activeScope = tree;
  for (const ancestor of ancestors) {
    if (functionTypes.has(ancestor.type)) {
      activeScope = ancestor;
    }
  }
  scopeByNode.set(node, activeScope);
  if (activeScope !== tree && !parentScope.has(activeScope)) {
    const parent = ancestors
      .slice()
      .reverse()
      .find(
        item => functionTypes.has(item.type) && item !== activeScope,
      );
    parentScope.set(activeScope, parent || tree);
  }
});

function aliasIsVisible(name, node) {
  let scope = scopeByNode.get(node) || tree;
  while (scope) {
    const owners = aliasScopes.get(name);
    if (owners && owners.has(scope)) return true;
    scope = parentScope.get(scope);
  }
  return false;
}

const assignments = [];
const destructuredTextAliases = new Map();

function collectDestructuredTextAliases(
  pattern,
  inheritedText = false,
  scope = tree,
) {
  if (!pattern) return;
  if (pattern.type === 'Identifier') {
    if (inheritedText) {
      if (!destructuredTextAliases.has(pattern.name)) {
        destructuredTextAliases.set(pattern.name, new Set());
      }
      destructuredTextAliases.get(pattern.name).add(scope);
    }
    return;
  }
  if (pattern.type === 'AssignmentPattern') {
    collectDestructuredTextAliases(pattern.left, inheritedText, scope);
    return;
  }
  if (pattern.type === 'RestElement') {
    collectDestructuredTextAliases(
      pattern.argument,
      inheritedText,
      scope,
    );
    return;
  }
  if (pattern.type === 'ArrayPattern') {
    for (const element of pattern.elements) {
      collectDestructuredTextAliases(element, inheritedText, scope);
    }
    return;
  }
  if (pattern.type !== 'ObjectPattern') return;
  for (const property of pattern.properties) {
    if (property.type === 'RestElement') {
      collectDestructuredTextAliases(
        property.argument,
        inheritedText,
        scope,
      );
      continue;
    }
    const key = property.key;
    const keyName = (
      key.type === 'Identifier'
        ? key.name
        : key.type === 'Literal'
          ? key.value
          : null
    );
    collectDestructuredTextAliases(
      property.value,
      inheritedText || textNames.has(keyName),
      scope,
    );
  }
}

walk.simple(tree, {
  AssignmentExpression(node) {
    const scope = scopeByNode.get(node) || tree;
    if (node.left.type === 'Identifier') {
      assignments.push([node.left.name, node.right, scope]);
    } else if (
      node.left.type === 'ArrayPattern'
      && node.right.type === 'ArrayExpression'
    ) {
      node.left.elements.forEach((element, index) => {
        const value = node.right.elements[index];
        collectDestructuredTextAliases(
          element,
          containsRequestText(value),
          scope,
        );
      });
    } else {
      collectDestructuredTextAliases(node.left, false, scope);
    }
  },
  VariableDeclarator(node) {
    const scope = scopeByNode.get(node) || tree;
    if (node.id.type === 'Identifier' && node.init) {
      assignments.push([node.id.name, node.init, scope]);
      return;
    }
    if (
      node.id.type === 'ArrayPattern'
      && node.init
      && node.init.type === 'ArrayExpression'
    ) {
      node.id.elements.forEach((element, index) => {
        const value = node.init.elements[index];
        collectDestructuredTextAliases(
          element,
          containsRequestText(value),
          scope,
        );
      });
      return;
    }
    collectDestructuredTextAliases(node.id, false, scope);
  },
});

const cjkAliases = new Set();
const dispatchAliases = new Set();
const regexAliases = new Set();
const textAliases = new Set(destructuredTextAliases.keys());
const cjkCallableAliases = new Set();
const textCallableAliases = new Set();
const aliasScopes = new Map();

function registerAlias(set, name, scope) {
  set.add(name);
  if (!aliasScopes.has(name)) aliasScopes.set(name, new Set());
  aliasScopes.get(name).add(scope);
}

for (const [name, scopes] of destructuredTextAliases) {
  aliasScopes.set(name, new Set(scopes));
}

function hasUserText(node) {
  let found = false;
  if (!node) return false;
  walk.full(node, child => {
    if (
      (
        child.type === 'Identifier'
        && (
          textNames.has(child.name)
          || aliasIsVisible(child.name, child)
        )
      )
      || (
        child.type === 'MemberExpression'
        && textNames.has(propertyName(child))
      )
    ) {
      found = true;
    }
  });
  return found;
}

function isCjkChoice(node) {
  return Boolean(
    node
    && (
      containsCjk(node)
      || (
        node.type === 'Identifier'
        && aliasIsVisible(node.name, node)
      )
    )
  );
}

function isDispatchChoice(node) {
  return Boolean(
    node
    && (
      objectHasCjkKey(node)
      || (
        node.type === 'Identifier'
        && aliasIsVisible(node.name, node)
      )
    )
  );
}

function isRegexChoice(node) {
  return Boolean(
    node
    && (
      (
        node.type === 'Literal'
        && node.regex
        && cjk.test(node.regex.pattern)
      )
      || (
        node.type === 'Identifier'
        && aliasIsVisible(node.name, node)
      )
      || (
        node.type === 'NewExpression'
        && node.callee.type === 'Identifier'
        && node.callee.name === 'RegExp'
        && node.arguments.some(isCjkChoice)
      )
    )
  );
}

function callableKind(node) {
  if (!node) return null;
  if (node.type === 'Identifier') {
    if (
      aliasIsVisible(node.name, node)
      && cjkCallableAliases.has(node.name)
    ) return 'cjk';
    if (
      aliasIsVisible(node.name, node)
      && textCallableAliases.has(node.name)
    ) return 'text';
    return null;
  }
  if (node.type === 'MemberExpression') {
    const method = propertyName(node);
    if (
      (textMethods.has(method) || regexMethods.has(method))
      && isCjkChoice(node.object)
    ) {
      return 'cjk';
    }
    if (textMethods.has(method) && hasUserText(node.object)) {
      return 'text';
    }
    return null;
  }
  if (
    node.type === 'CallExpression'
    && node.callee.type === 'MemberExpression'
    && propertyName(node.callee) === 'bind'
  ) {
    return callableKind(node.callee.object);
  }
  return null;
}

let changed = true;
while (changed) {
  const before = [
    cjkAliases.size,
    dispatchAliases.size,
    regexAliases.size,
    textAliases.size,
    cjkCallableAliases.size,
    textCallableAliases.size,
  ].join(':');
  for (const [name, value, scope] of assignments) {
    if (isCjkChoice(value)) registerAlias(cjkAliases, name, scope);
    if (isDispatchChoice(value)) {
      registerAlias(dispatchAliases, name, scope);
    }
    if (isRegexChoice(value)) registerAlias(regexAliases, name, scope);
    if (hasUserText(value)) registerAlias(textAliases, name, scope);
    const kind = callableKind(value);
    if (kind === 'cjk') {
      registerAlias(cjkCallableAliases, name, scope);
    }
    if (kind === 'text') {
      registerAlias(textCallableAliases, name, scope);
    }
  }
  const after = [
    cjkAliases.size,
    dispatchAliases.size,
    regexAliases.size,
    textAliases.size,
    cjkCallableAliases.size,
    textCallableAliases.size,
  ].join(':');
  changed = before !== after;
}

const violations = [];
function report(node, message) {
  violations.push({
    endLine: node.loc.end.line,
    line: node.loc.start.line,
    message,
  });
}

walk.full(tree, node => {
  if (
    node.type === 'BinaryExpression'
    && ['==', '===', '!=', '!=='].includes(node.operator)
    && (
      (hasUserText(node.left) && isCjkChoice(node.right))
      || (hasUserText(node.right) && isCjkChoice(node.left))
    )
  ) {
    report(node, 'literal sentence branch');
    return;
  }
  if (
    node.type === 'MemberExpression'
    && node.computed
    && isDispatchChoice(node.object)
    && hasUserText(node.property)
  ) {
    report(node, 'literal sentence dispatch');
    return;
  }
  if (
    node.type === 'SwitchStatement'
    && hasUserText(node.discriminant)
    && node.cases.some(item => isCjkChoice(item.test))
  ) {
    report(node, 'literal sentence branch');
    return;
  }
  if (node.type !== 'CallExpression') return;
  const directMethod = propertyName(node.callee);
  if (
    node.callee.type === 'MemberExpression'
    && ['apply', 'call'].includes(directMethod)
    && node.callee.object.type === 'MemberExpression'
    && textMethods.has(propertyName(node.callee.object))
    && hasUserText(node.arguments[0])
    && node.arguments.slice(1).some(isCjkChoice)
  ) {
    report(node, 'literal sentence helper');
    return;
  }
  if (
    node.callee.type === 'MemberExpression'
    && ['endsWith', 'includes', 'startsWith'].includes(directMethod)
    && hasUserText(node.callee.object)
    && node.arguments.some(isCjkChoice)
  ) {
    report(node, 'literal sentence branch');
    return;
  }
  if (
    node.callee.type === 'MemberExpression'
    && regexMethods.has(directMethod)
    && isRegexChoice(node.callee.object)
    && node.arguments.some(hasUserText)
  ) {
    report(node, 'literal sentence regex');
    return;
  }
  if (
    node.callee.type === 'MemberExpression'
    && ['match', 'matchAll', 'search'].includes(directMethod)
    && hasUserText(node.callee.object)
    && node.arguments.some(argument => (
      isRegexChoice(argument) || isCjkChoice(argument)
    ))
  ) {
    report(node, 'literal sentence regex');
    return;
  }
  if (
    node.callee.type === 'MemberExpression'
    && ['replace', 'replaceAll'].includes(directMethod)
    && hasUserText(node.callee.object)
    && node.arguments.some(isCjkChoice)
  ) {
    report(node, 'literal output replacement');
    return;
  }
  const indirectKind = callableKind(node.callee);
  if (
    (indirectKind === 'cjk' && node.arguments.some(hasUserText))
    || (indirectKind === 'text' && node.arguments.some(isCjkChoice))
  ) {
    report(node, 'literal sentence helper');
  }
});

violations.sort((left, right) => (
  left.line - right.line
  || left.endLine - right.endLine
  || left.message.localeCompare(right.message)
));
process.stdout.write(JSON.stringify(violations));
"""


class _InlineScriptCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.sources: list[tuple[int, str]] = []
        self._collecting = False

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        if tag.lower() != "script":
            return
        self._collecting = all(
            name.lower() != "src"
            for name, _ in attrs
        )

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "script":
            self._collecting = False

    def handle_data(self, data: str) -> None:
        if self._collecting and data.strip():
            self.sources.append((self.getpos()[0], data))


def _target_names(node: ast.AST) -> set[str]:
    if isinstance(node, ast.Name):
        return {node.id}
    if isinstance(node, (ast.Tuple, ast.List)):
        return {
            name
            for item in node.elts
            for name in _target_names(item)
        }
    return set()


def _has_product_id(node: ast.AST, aliases: set[str]) -> bool:
    return (
        isinstance(node, ast.Name)
        and (
            node.id in aliases
            or node.id == "product_id"
            or node.id.endswith("_product_id")
        )
    ) or (
        isinstance(node, ast.Attribute)
        and (
            node.attr == "product_id"
            or node.attr.endswith("_product_id")
        )
    )


def _has_user_text(
    node: ast.AST,
    aliases: set[str] | frozenset[str] = frozenset(),
) -> bool:
    return any(
        (
            isinstance(item, ast.Name)
            and (
                item.id in _TEXT_NAMES
                or item.id in aliases
            )
        )
        or (
            isinstance(item, ast.Attribute)
            and item.attr in _TEXT_NAMES
        )
        for item in ast.walk(node)
    )


def _is_literal_choice(node: ast.AST, aliases: set[str]) -> bool:
    if isinstance(node, ast.Constant):
        return (
            isinstance(node.value, int)
            and not isinstance(node.value, bool)
            and node.value > 0
        ) or (
            isinstance(node.value, str)
            and bool(node.value)
        )
    if isinstance(node, (ast.List, ast.Set, ast.Tuple)):
        return bool(node.elts) and all(
            _is_literal_choice(item, aliases)
            for item in node.elts
        )
    return isinstance(node, ast.Name) and node.id in aliases


def _contains_cjk_literal(node: ast.AST) -> bool:
    return any(
        isinstance(item, ast.Constant)
        and isinstance(item.value, str)
        and len(_CJK.findall(item.value)) >= 2
        for item in ast.walk(node)
    )


def _contains_cjk_choice(
    node: ast.AST,
    aliases: set[str],
) -> bool:
    return _contains_cjk_literal(node) or (
        isinstance(node, ast.Name) and node.id in aliases
    )


def _python_callable_kind(
    node: ast.AST,
    *,
    cjk_aliases: set[str],
    cjk_callable_aliases: set[str],
    text_aliases: set[str],
    text_callable_aliases: set[str],
) -> str | None:
    if isinstance(node, ast.Name):
        if node.id in cjk_callable_aliases:
            return "cjk"
        if node.id in text_callable_aliases:
            return "text"
        return None
    if (
        isinstance(node, ast.Attribute)
        and node.attr in _PYTHON_TEXT_METHODS
    ):
        if _contains_cjk_choice(node.value, cjk_aliases):
            return "cjk"
        if _has_user_text(node.value, text_aliases):
            return "text"
    return None


def _python_predicate_helpers(tree: ast.AST) -> set[str]:
    helpers: set[str] = set()
    for function in ast.walk(tree):
        if not isinstance(
            function,
            (ast.FunctionDef, ast.AsyncFunctionDef),
        ):
            continue
        parameters = {
            argument.arg
            for argument in (
                *function.args.posonlyargs,
                *function.args.args,
                *function.args.kwonlyargs,
            )
        }
        if len(parameters) < 2:
            continue
        for node in ast.walk(function):
            if isinstance(node, ast.Compare):
                operands = (node.left, *node.comparators)
                if (
                    any(
                        isinstance(operator, (ast.Eq, ast.NotEq, ast.In, ast.NotIn))
                        for operator in node.ops
                    )
                    and sum(
                        any(
                            isinstance(item, ast.Name)
                            and item.id in parameters
                            for item in ast.walk(operand)
                        )
                        for operand in operands
                    )
                    >= 2
                ):
                    helpers.add(function.name)
                    break
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in _PYTHON_TEXT_METHODS
                and _has_user_text(node, parameters)
            ):
                helpers.add(function.name)
                break
    return helpers


def _python_scope_by_node(tree: ast.AST) -> dict[int, ast.AST]:
    result: dict[int, ast.AST] = {}
    scope_types = (
        ast.AsyncFunctionDef,
        ast.ClassDef,
        ast.FunctionDef,
        ast.Lambda,
    )

    def visit(node: ast.AST, scope: ast.AST) -> None:
        active_scope = (
            node
            if node is not tree and isinstance(node, scope_types)
            else scope
        )
        result[id(node)] = active_scope
        for child in ast.iter_child_nodes(node):
            visit(child, active_scope)

    visit(tree, tree)
    return result


def _python_call_values(node: ast.Call) -> tuple[ast.AST, ...]:
    return (
        *node.args,
        *(keyword.value for keyword in node.keywords),
    )


def _overlaps_added(node: ast.AST, added_lines: set[int]) -> bool:
    start = getattr(node, "lineno", 0)
    end = getattr(node, "end_lineno", start)
    return any(line in added_lines for line in range(start, end + 1))


def _contains_named_alias(node: ast.AST, names: set[str]) -> bool:
    return any(
        isinstance(item, ast.Name) and item.id in names
        for item in ast.walk(node)
    )


def _python_source_violations(
    source: str,
    *,
    added_lines: set[int] | None = None,
) -> tuple[str, ...]:
    tree = ast.parse(source)
    selected_lines = (
        added_lines
        if added_lines is not None
        else set(range(1, len(source.splitlines()) + 1))
    )
    scope_by_node = _python_scope_by_node(tree)
    predicate_helpers = _python_predicate_helpers(tree)
    aliases_by_scope = {
        id(scope): {
            "product": set(),
            "literal": set(),
            "cjk": set(),
            "regex": set(),
            "cjk_callable": set(),
            "text": set(),
            "text_callable": set(),
            "predicate_callable": set(predicate_helpers),
        }
        for scope in set(scope_by_node.values())
    }

    assignments = tuple(
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.NamedExpr))
        and node.value is not None
    )
    changed = True
    while changed:
        changed = False
        for node in assignments:
            scope = scope_by_node[id(node)]
            aliases = aliases_by_scope[id(scope)]
            module_aliases = aliases_by_scope[id(tree)]
            product_aliases = aliases["product"] | module_aliases["product"]
            literal_aliases = aliases["literal"] | module_aliases["literal"]
            cjk_literal_aliases = aliases["cjk"] | module_aliases["cjk"]
            cjk_regex_aliases = aliases["regex"] | module_aliases["regex"]
            cjk_callable_aliases = (
                aliases["cjk_callable"]
                | module_aliases["cjk_callable"]
            )
            text_aliases = aliases["text"] | module_aliases["text"]
            text_callable_aliases = (
                aliases["text_callable"]
                | module_aliases["text_callable"]
            )
            predicate_callable_aliases = (
                aliases["predicate_callable"]
                | module_aliases["predicate_callable"]
            )
            value = node.value
            targets = (
                node.targets
                if isinstance(node, ast.Assign)
                else (node.target,)
            )
            names = {
                name
                for target in targets
                for name in _target_names(target)
            }
            before = (
                len(aliases["product"]),
                len(aliases["literal"]),
                len(aliases["cjk"]),
                len(aliases["regex"]),
                len(aliases["cjk_callable"]),
                len(aliases["text"]),
                len(aliases["text_callable"]),
                len(aliases["predicate_callable"]),
            )
            if _has_product_id(value, product_aliases):
                aliases["product"].update(names)
            if _is_literal_choice(value, literal_aliases):
                aliases["literal"].update(names)
            if _contains_cjk_choice(value, cjk_literal_aliases):
                aliases["cjk"].update(names)
            if _has_user_text(value, text_aliases):
                aliases["text"].update(names)
            if (
                isinstance(value, ast.Call)
                and (
                    (
                        isinstance(value.func, ast.Attribute)
                        and isinstance(value.func.value, ast.Name)
                        and value.func.value.id == "re"
                        and value.func.attr == "compile"
                    )
                    or (
                        isinstance(value.func, ast.Name)
                        and value.func.id == "compile"
                    )
                )
                and any(
                    _contains_cjk_choice(arg, cjk_literal_aliases)
                    for arg in value.args
                )
            ):
                aliases["regex"].update(names)
            callable_kind = _python_callable_kind(
                value,
                cjk_aliases=cjk_literal_aliases,
                cjk_callable_aliases=cjk_callable_aliases,
                text_aliases=text_aliases,
                text_callable_aliases=text_callable_aliases,
            )
            if callable_kind == "cjk":
                aliases["cjk_callable"].update(names)
            elif callable_kind == "text":
                aliases["text_callable"].update(names)
            if (
                isinstance(value, ast.Name)
                and value.id in predicate_callable_aliases
            ):
                aliases["predicate_callable"].update(names)
            changed = changed or before != (
                len(aliases["product"]),
                len(aliases["literal"]),
                len(aliases["cjk"]),
                len(aliases["regex"]),
                len(aliases["cjk_callable"]),
                len(aliases["text"]),
                len(aliases["text_callable"]),
                len(aliases["predicate_callable"]),
            )

    added_sentence_aliases: set[str] = set()
    if added_lines is not None:
        for assignment in assignments:
            if not _overlaps_added(assignment, selected_lines):
                continue
            if _contains_cjk_literal(assignment.value):
                targets = (
                    assignment.targets
                    if isinstance(assignment, ast.Assign)
                    else (assignment.target,)
                )
                added_sentence_aliases.update(
                    name
                    for target in targets
                    for name in _target_names(target)
                )

    violations: list[str] = []
    for node in ast.walk(tree):
        aliases = aliases_by_scope[id(scope_by_node[id(node)])]
        module_aliases = aliases_by_scope[id(tree)]
        product_aliases = aliases["product"] | module_aliases["product"]
        literal_aliases = aliases["literal"] | module_aliases["literal"]
        cjk_literal_aliases = aliases["cjk"] | module_aliases["cjk"]
        cjk_regex_aliases = aliases["regex"] | module_aliases["regex"]
        cjk_callable_aliases = (
            aliases["cjk_callable"]
            | module_aliases["cjk_callable"]
        )
        text_aliases = aliases["text"] | module_aliases["text"]
        text_callable_aliases = (
            aliases["text_callable"]
            | module_aliases["text_callable"]
        )
        predicate_callable_aliases = (
            aliases["predicate_callable"]
            | module_aliases["predicate_callable"]
        )
        if (
            not _overlaps_added(node, selected_lines)
            and not _contains_named_alias(node, added_sentence_aliases)
        ):
            continue
        if isinstance(node, ast.Compare):
            operands = (node.left, *node.comparators)
            for left, operator, right in zip(
                operands,
                node.ops,
                operands[1:],
            ):
                if (
                    isinstance(
                        operator,
                        (ast.Eq, ast.NotEq, ast.In, ast.NotIn),
                    )
                    and (
                        (
                            _has_product_id(left, product_aliases)
                            and _is_literal_choice(
                                right,
                                literal_aliases,
                            )
                        )
                        or (
                            _has_product_id(right, product_aliases)
                            and _is_literal_choice(
                                left,
                                literal_aliases,
                            )
                        )
                    )
                ):
                    violations.append(
                        f"literal product-id branch at line {node.lineno}"
                    )
                if (
                    _has_user_text(left, text_aliases)
                    and _contains_cjk_choice(
                        right,
                        cjk_literal_aliases,
                    )
                ) or (
                    _has_user_text(right, text_aliases)
                    and _contains_cjk_choice(
                        left,
                        cjk_literal_aliases,
                    )
                ):
                    violations.append(
                        f"literal sentence branch at line {node.lineno}"
                    )
        if (
            isinstance(node, ast.Match)
            and _has_user_text(node.subject, text_aliases)
        ):
            for case in node.cases:
                if _contains_cjk_choice(
                    case.pattern,
                    cjk_literal_aliases,
                ):
                    violations.append(
                        "literal sentence branch at line "
                        f"{case.pattern.lineno}"
                    )
        if (
            isinstance(node, ast.Subscript)
            and _contains_cjk_choice(
                node.value,
                cjk_literal_aliases,
            )
            and _has_user_text(node.slice, text_aliases)
        ):
            violations.append(
                f"literal sentence dispatch at line {node.lineno}"
            )
            continue
        if not isinstance(node, ast.Call):
            continue
        call_values = _python_call_values(node)
        callable_kind = _python_callable_kind(
            node.func,
            cjk_aliases=cjk_literal_aliases,
            cjk_callable_aliases=cjk_callable_aliases,
            text_aliases=text_aliases,
            text_callable_aliases=text_callable_aliases,
        )
        if isinstance(node.func, ast.Name) and (
            (
                callable_kind == "cjk"
                and any(
                    _has_user_text(arg, text_aliases)
                    for arg in call_values
                )
            )
            or (
                callable_kind == "text"
                and any(
                    _contains_cjk_choice(
                        arg,
                        cjk_literal_aliases,
                    )
                    for arg in call_values
                )
            )
        ):
            violations.append(
                f"literal sentence helper at line {node.lineno}"
            )
            continue
        if (
            isinstance(node.func, ast.Attribute)
            and node.func.attr in {"startswith", "endswith"}
            and _has_user_text(node.func.value, text_aliases)
            and any(
                _contains_cjk_choice(arg, cjk_literal_aliases)
                for arg in call_values
            )
        ):
            violations.append(
                f"literal sentence branch at line {node.lineno}"
            )
            continue
        if (
            isinstance(node.func, ast.Attribute)
            and node.func.attr in {"get", "setdefault"}
            and _contains_cjk_choice(
                node.func.value,
                cjk_literal_aliases,
            )
            and any(
                _has_user_text(arg, text_aliases)
                for arg in call_values
            )
        ):
            violations.append(
                f"literal sentence dispatch at line {node.lineno}"
            )
            continue
        if (
            isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id in cjk_regex_aliases
            and node.func.attr in {"findall", "fullmatch", "match", "search"}
            and _has_user_text(node, text_aliases)
        ):
            violations.append(
                f"literal sentence regex at line {node.lineno}"
            )
            continue
        if (
            isinstance(node.func, ast.Name)
            and node.func.id in predicate_callable_aliases
            and _has_user_text(node, text_aliases)
            and any(
                _contains_cjk_choice(arg, cjk_literal_aliases)
                for arg in call_values
            )
        ):
            violations.append(
                f"literal sentence helper at line {node.lineno}"
            )
            continue
        if (
            isinstance(node.func, ast.Attribute)
            and node.func.attr == "replace"
            and _has_user_text(node.func.value, text_aliases)
            and any(_contains_cjk_literal(arg) for arg in call_values)
        ):
            violations.append(
                f"literal output replacement at line {node.lineno}"
            )
        if (
            isinstance(node.func, ast.Attribute)
            and node.func.attr in {"findall", "fullmatch", "match", "search"}
            and _has_user_text(node, text_aliases)
            and any(_contains_cjk_literal(arg) for arg in call_values)
        ):
            violations.append(
                f"literal sentence regex at line {node.lineno}"
            )
    return tuple(dict.fromkeys(violations))


def _javascript_source_violations(
    source: str,
    *,
    line_offset: int = 1,
    added_lines: set[int] | None = None,
) -> tuple[str, ...]:
    completed = subprocess.run(
        [
            "node",
            "--expose-internals",
            "-e",
            _JAVASCRIPT_AST_GATE,
        ],
        input=source,
        check=True,
        capture_output=True,
        text=True,
    )
    rows = json.loads(completed.stdout)
    if not isinstance(rows, list):
        raise AssertionError("JavaScript AST gate returned invalid output")
    selected_lines = (
        added_lines
        if added_lines is not None
        else set(
            range(
                line_offset,
                line_offset + len(source.splitlines()),
            )
        )
    )
    violations: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            raise AssertionError(
                "JavaScript AST gate returned invalid violation"
            )
        start = row.get("line")
        end = row.get("endLine")
        message = row.get("message")
        if (
            not isinstance(start, int)
            or not isinstance(end, int)
            or not isinstance(message, str)
        ):
            raise AssertionError(
                "JavaScript AST gate returned invalid violation"
            )
        start += line_offset - 1
        end += line_offset - 1
        if not any(
            line in selected_lines
            for line in range(start, end + 1)
        ):
            continue
        violations.append(f"{message} at line {start}")
    return tuple(dict.fromkeys(violations))


def _inline_javascript_sources(
    html: str,
) -> tuple[tuple[int, str], ...]:
    parser = _InlineScriptCollector()
    parser.feed(html)
    parser.close()
    return tuple(parser.sources)


def _added_lines_by_path(diff: str) -> dict[str, set[int]]:
    result: dict[str, set[int]] = {}
    current_path: str | None = None
    next_line: int | None = None
    for line in diff.splitlines():
        if line.startswith("+++ b/"):
            current_path = line[6:]
            result.setdefault(current_path, set())
            continue
        match = _HUNK.match(line)
        if match is not None:
            next_line = int(match.group(1))
            continue
        if current_path is None or next_line is None:
            continue
        if line.startswith("+") and not line.startswith("+++"):
            result[current_path].add(next_line)
            next_line += 1
        elif line.startswith("-") and not line.startswith("---"):
            continue
        else:
            next_line += 1
    return result


@pytest.mark.parametrize(
    ("source", "expected"),
    (
        (
            "def f(item, product_id):\n"
            "    return item.product_id == product_id\n",
            (),
        ),
        (
            "def f(item, product_ids):\n"
            "    return item.product_id == product_ids[0]\n",
            (),
        ),
        (
            "def f(product_id):\n"
            "    return product_id <= 0\n",
            (),
        ),
        (
            "def f(item):\n"
            "    return item.product_id == 38\n",
            ("literal product-id branch at line 2",),
        ),
        (
            "def f(item):\n"
            "    return 'product-38' == item.product_id\n",
            ("literal product-id branch at line 2",),
        ),
        (
            "SPECIAL_IDS = {38, 51}\n"
            "def f(item):\n"
            "    return item.product_id in SPECIAL_IDS\n",
            ("literal product-id branch at line 3",),
        ),
        (
            "def f(message):\n"
            "    return '最适合' in message\n",
            ("literal sentence branch at line 2",),
        ),
        (
            "def f(message):\n"
            "    return message.startswith('最适合')\n",
            ("literal sentence branch at line 2",),
        ),
        (
            "def f(message):\n"
            "    return {'最适合': 'fit'}.get(message)\n",
            ("literal sentence dispatch at line 2",),
        ),
        (
            "PATTERN = re.compile('最适合')\n"
            "def f(message):\n"
            "    return PATTERN.search(message)\n",
            ("literal sentence regex at line 3",),
        ),
        (
            "def f(message):\n"
            "    return matches(message, '最适合')\n",
            (),
        ),
        (
            "def matches(value, token):\n"
            "    return token in value\n"
            "def f(message):\n"
            "    return matches(message, '最适合')\n",
            ("literal sentence helper at line 4",),
        ),
        (
            "def matches(value, token):\n"
            "    return token in value\n"
            "def f(message):\n"
            "    return matches(value=message, token='最适合')\n",
            ("literal sentence helper at line 4",),
        ),
        (
            "def f(message):\n"
            "    query = message\n"
            "    return '最适合' in query\n",
            ("literal sentence branch at line 3",),
        ),
        (
            "def f(message):\n"
            "    if query := message:\n"
            "        return '最适合' in query\n",
            ("literal sentence branch at line 3",),
        ),
        (
            "def capture(message):\n"
            "    query = message\n"
            "    return query\n"
            "def choose(query):\n"
            "    return query == '最适合'\n",
            (),
        ),
        (
            "def f(message):\n"
            "    match message:\n"
            "        case '最适合':\n"
            "            return 'fit'\n",
            ("literal sentence branch at line 3",),
        ),
        (
            "def f(message, rows):\n"
            "    return [row for row in rows "
            "if message.endswith('最适合')]\n",
            ("literal sentence branch at line 2",),
        ),
        (
            "TOKEN = '最适合'\n"
            "def f(message):\n"
            "    return message.endswith(TOKEN)\n",
            ("literal sentence branch at line 3",),
        ),
        (
            "RULES = {'最适合': 'fit'}\n"
            "def f(message):\n"
            "    return RULES.get(message)\n",
            ("literal sentence dispatch at line 3",),
        ),
        (
            "RULES = {'最适合': 'fit'}\n"
            "def f(message):\n"
            "    return RULES[message]\n",
            ("literal sentence dispatch at line 3",),
        ),
        (
            "MATCH = '最适合'.__eq__\n"
            "def f(message):\n"
            "    return MATCH(message)\n",
            ("literal sentence helper at line 3",),
        ),
        (
            "PHRASES = {'最适合'}\n"
            "def f(message):\n"
            "    return message in PHRASES\n",
            ("literal sentence branch at line 3",),
        ),
    ),
)
def test_python_gate_distinguishes_literal_rules_from_normal_bindings(
    source: str,
    expected: tuple[str, ...],
) -> None:
    assert _python_source_violations(source) == expected


def test_python_gate_traces_added_sentence_source_into_existing_sink() -> None:
    source = (
        "TOKEN = '最适合'\n"
        "def f(message):\n"
        "    return message.startswith(TOKEN)\n"
    )

    violations = _python_source_violations(
        source,
        added_lines={1},
    )

    assert "literal sentence branch at line 3" in violations


def test_python_gate_allows_class_level_dimension_aliases() -> None:
    source = (
        "ALIASES = {'usage': ('怎么用', '怎么涂')}\n"
        "def resolve(question):\n"
        "    return tuple(\n"
        "        key for key, values in ALIASES.items()\n"
        "        if any(value in question for value in values)\n"
        "    )\n"
    )

    assert _python_source_violations(source) == ()


@pytest.mark.parametrize(
    ("source", "expected"),
    (
        (
            "function f(message) {\n"
            "  return message.includes('给我挑一个');\n"
            "}\n",
            ("literal sentence branch at line 2",),
        ),
        (
            "function f(message) {\n"
            "  return /给我挑一个/.test(message);\n"
            "}\n",
            ("literal sentence regex at line 2",),
        ),
        (
            "const RULES = {'给我挑一个': 'fit'};\n"
            "function f(message) {\n"
            "  return RULES[message];\n"
            "}\n",
            ("literal sentence dispatch at line 3",),
        ),
        (
            "const TOKEN = '给我挑一个';\n"
            "function f(message) {\n"
            "  return message.startsWith(TOKEN);\n"
            "}\n",
            ("literal sentence branch at line 3",),
        ),
        (
            "const MATCH = '给我挑一个'.includes.bind('给我挑一个');\n"
            "function f(message) {\n"
            "  return MATCH(message);\n"
            "}\n",
            ("literal sentence helper at line 3",),
        ),
        (
            "function f(message) {\n"
            "  switch (message) {\n"
            "    case '给我挑一个': return 'fit';\n"
            "    default: return 'explore';\n"
            "  }\n"
            "}\n",
            ("literal sentence branch at line 2",),
        ),
        (
            "function f(payload) {\n"
            "  const {message: query} = payload;\n"
            "  return query.includes('给我挑一个');\n"
            "}\n",
            ("literal sentence branch at line 3",),
        ),
        (
            "function f(payload) {\n"
            "  let query;\n"
            "  ({message: query} = payload);\n"
            "  return query.includes('给我挑一个');\n"
            "}\n",
            ("literal sentence branch at line 4",),
        ),
        (
            "function f(payload) {\n"
            "  const {message: query = ''} = payload;\n"
            "  return query.includes('给我挑一个');\n"
            "}\n",
            ("literal sentence branch at line 3",),
        ),
        (
            "function f(payload) {\n"
            "  const {data: {message: query}} = payload;\n"
            "  return query.includes('给我挑一个');\n"
            "}\n",
            ("literal sentence branch at line 3",),
        ),
        (
            "function f(message) {\n"
            "  return String.prototype.includes.call(\n"
            "    message,\n"
            "    '给我挑一个'\n"
            "  );\n"
            "}\n",
            ("literal sentence helper at line 2",),
        ),
        (
            "function f(message) {\n"
            "  emit('用户消息: %s', message);\n"
            "}\n",
            (),
        ),
    ),
)
def test_javascript_gate_rejects_literal_text_dispatch(
    source: str,
    expected: tuple[str, ...],
) -> None:
    assert _javascript_source_violations(source) == expected


def test_javascript_gate_tracks_array_destructured_request_text() -> None:
    source = (
        "function f(payload) {\n"
        "  const [query] = [payload.message];\n"
        "  return query.includes('最适合');\n"
        "}\n"
    )

    violations = _javascript_source_violations(source)

    assert any("literal sentence branch" in item for item in violations)


def test_javascript_gate_does_not_leak_aliases_between_functions() -> None:
    source = (
        "function first(payload) {\n"
        "  const query = payload.message;\n"
        "  return query;\n"
        "}\n"
        "function second() {\n"
        "  return query.includes('最适合');\n"
        "}\n"
    )

    assert _javascript_source_violations(source) == ()


def test_html_inline_script_uses_source_file_line_numbers() -> None:
    html = (
        "<script>\n"
        "function f(message) {\n"
        "  return message.includes('最适合');\n"
        "}\n"
        "</script>\n"
    )
    scripts = _inline_javascript_sources(html)

    assert len(scripts) == 1
    line_offset, source = scripts[0]
    assert _javascript_source_violations(
        source,
        line_offset=line_offset,
        added_lines={3},
    ) == ("literal sentence branch at line 3",)


def test_release_change_does_not_add_sentence_owned_action_rules() -> None:
    diff = subprocess.run(
        ["git", "diff", "-U0", "HEAD", "--", *PRODUCTION],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    added_by_path = _added_lines_by_path(diff)
    violations: list[str] = []
    for relative, added_lines in added_by_path.items():
        path = ROOT / relative
        if path.suffix == ".py":
            violations.extend(
                f"{relative}: {violation}"
                for violation in _python_source_violations(
                    path.read_text(encoding="utf-8"),
                    added_lines=added_lines,
                )
            )
            continue
        source = path.read_text(encoding="utf-8")
        javascript_sources = (
            _inline_javascript_sources(source)
            if path.suffix == ".html"
            else ((0, source),)
        )
        for line_offset, javascript in javascript_sources:
            violations.extend(
                f"{relative}: {violation}"
                for violation in _javascript_source_violations(
                    javascript,
                    line_offset=line_offset,
                    added_lines=added_lines,
                )
            )
    assert sorted(violations) == []
