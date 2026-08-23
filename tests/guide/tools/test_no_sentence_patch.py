from __future__ import annotations

import ast
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
    "app/static/chat.html",
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


def _has_user_text(node: ast.AST) -> bool:
    return any(
        (
            isinstance(item, ast.Name)
            and item.id in _TEXT_NAMES
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
        and _CJK.search(item.value) is not None
        for item in ast.walk(node)
    )


def _overlaps_added(node: ast.AST, added_lines: set[int]) -> bool:
    start = getattr(node, "lineno", 0)
    end = getattr(node, "end_lineno", start)
    return any(line in added_lines for line in range(start, end + 1))


def _python_source_violations(
    source: str,
    *,
    added_lines: set[int] | None = None,
) -> tuple[str, ...]:
    tree = ast.parse(source)
    selected_lines = added_lines or set(
        range(1, len(source.splitlines()) + 1)
    )
    product_aliases: set[str] = set()
    literal_aliases: set[str] = set()

    for node in ast.walk(tree):
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
        names = {
            name
            for target in targets
            for name in _target_names(target)
        }
        if _has_product_id(value, product_aliases):
            product_aliases.update(names)
        if _is_literal_choice(value, literal_aliases):
            literal_aliases.update(names)

    violations: list[str] = []
    for node in ast.walk(tree):
        if not _overlaps_added(node, selected_lines):
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
                    _has_user_text(left)
                    and _contains_cjk_literal(right)
                ) or (
                    _has_user_text(right)
                    and _contains_cjk_literal(left)
                ):
                    violations.append(
                        f"literal sentence branch at line {node.lineno}"
                    )
        if not isinstance(node, ast.Call):
            continue
        if (
            isinstance(node.func, ast.Attribute)
            and node.func.attr == "replace"
            and _has_user_text(node.func.value)
            and any(_contains_cjk_literal(arg) for arg in node.args)
        ):
            violations.append(
                f"literal output replacement at line {node.lineno}"
            )
        if (
            isinstance(node.func, ast.Attribute)
            and node.func.attr in {"findall", "fullmatch", "match", "search"}
            and _has_user_text(node)
            and any(_contains_cjk_literal(arg) for arg in node.args)
        ):
            violations.append(
                f"literal sentence regex at line {node.lineno}"
            )
    return tuple(dict.fromkeys(violations))


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
    ),
)
def test_python_gate_distinguishes_literal_rules_from_normal_bindings(
    source: str,
    expected: tuple[str, ...],
) -> None:
    assert _python_source_violations(source) == expected


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
        for line_number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(),
            start=1,
        ):
            if line_number not in added_lines:
                continue
            if (
                any(
                    token in line
                    for token in (
                        "第一款和第二款",
                        "第一张和第二张",
                        "哪个更适合",
                        "推荐一款",
                        "最适合",
                        "适合我",
                    )
                )
                and any(
                    marker in line
                    for marker in ("if", "?", ".replace(", ".match(")
                )
            ):
                violations.append(
                    f"{relative}: literal sentence rule at line "
                    f"{line_number}"
                )
    assert violations == []
