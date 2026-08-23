#!/usr/bin/env python3
"""Run the mechanically independent Task 11 r5 evidence audit."""

from __future__ import annotations

import argparse
import ast
import fnmatch
from hashlib import sha256
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import tempfile
from typing import Any, Mapping, Sequence


REPORT_SCHEMA = "guide-task11-independent-audit-v1"
MANIFEST_SCHEMA = "guide-task11-candidate-manifest-v1"
PLAN_REVISION = "2026-08-23-task11-r5"
FIXTURE_TURNS = (
    "fixture-explore-recommendation",
    "fixture-fit-recommendation",
    "fixture-product-knowledge",
    "fixture-comparison",
    "fixture-image-identity",
    "fixture-image-fit-recommendation",
    "fixture-multi-image-comparison",
)
MANIFEST_CATEGORIES = (
    "source_paths",
    "test_paths",
    "tool_paths",
    "plan_paths",
    "fixture_paths",
)
SUMMARY_ZERO_FIELDS = (
    "actual_equivalence_failure_count",
    "bounded_failure_count",
    "compiler_bypass_count",
    "compiler_call_count_violation_count",
    "structured_understanding_injection_count",
    "direct_router_bypass_count",
    "legacy_entrypoint_count",
    "router_call_count_violation_count",
    "decision_identity_violation_count",
    "selected_processor_invocation_count_violation_count",
    "nonselected_processor_invocation_count",
    "execution_result_count_violation_count",
    "reducer_call_count_violation_count",
    "processor_state_write_count",
    "event_state_projection_count",
    "state_save_count_violation_count",
    "terminal_contract_failure_count",
    "state_transition_failure_count",
    "outbound_network_attempt_count",
    "provider_call_count",
)
TRACE_ZERO_FIELDS = (
    "structured_understanding_injection_count",
    "direct_router_bypass_count",
    "legacy_entrypoint_count",
    "decision_identity_violation_count",
    "processor_state_write_count",
    "event_state_projection_count",
    "provider_call_count",
    "outbound_network_attempt_count",
)
BRIDGE_SYMBOLS = frozenset(
    {
        "ChatOwner",
        "bind_execution_profile_owner",
        "classify_chat_owner",
        "collect_guide_chat_response",
        "compatibility_dispatch",
        "compiler_bridge",
        "from_user_turn",
        "legacy_dispatch",
        "project_event_to_state",
        "route_bridge",
    }
)
LEGACY_FLAG_NAMES = frozenset(
    {
        "GUIDE_USE_LEGACY_ROUTER",
        "GUIDE_USE_UNIFIED_ROUTER",
        "LEGACY_GUIDE",
        "USE_LEGACY_GUIDE",
        "USE_UNIFIED_ROUTER",
    }
)
REQUIRED_BROWSER_FILES = frozenset(
    {
        "request.json",
        "stream.sse",
        "presentation-contract.json",
        "terminal-dom.json",
        "screenshot.png",
        "console.json",
        "network.json",
        "sandbox-audit.json",
    }
)
RELEVANT_PREFIXES = (
    "app/",
    "tests/",
    "tools/",
    "docs/superpowers/plans/",
)
HEX_40 = re.compile(r"^[0-9a-f]{40}$")
HEX_64 = re.compile(r"^[0-9a-f]{64}$")


class Task11IndependentAuditError(RuntimeError):
    """Raised when a required Task 11 fact cannot be proved."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise Task11IndependentAuditError(message)


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _required_int(
    payload: Mapping[str, object],
    key: str,
    *,
    label: str,
) -> int:
    value = payload.get(key)
    _require(_is_int(value), f"{label} field {key} is invalid")
    return int(value)


def _required_zero(
    payload: Mapping[str, object],
    key: str,
    *,
    label: str,
) -> None:
    _require(
        _required_int(payload, key, label=label) == 0,
        f"{label} field {key} must be zero",
    )


def _is_digest(value: object) -> bool:
    return isinstance(value, str) and HEX_64.fullmatch(value) is not None


def _digest_file(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _input_file(path: str | Path, *, label: str) -> Path:
    candidate = Path(path)
    if candidate.is_symlink():
        raise Task11IndependentAuditError(f"{label} cannot be a symlink")
    if not candidate.is_file():
        raise Task11IndependentAuditError(f"{label} is missing: {candidate}")
    return candidate.resolve()


def _load_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise Task11IndependentAuditError(
            f"{label} is not valid JSON"
        ) from exc
    if not isinstance(value, dict):
        raise Task11IndependentAuditError(f"{label} must be an object")
    return value


def _load_list(path: Path, *, label: str) -> list[Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise Task11IndependentAuditError(
            f"{label} is not valid JSON"
        ) from exc
    if not isinstance(value, list):
        raise Task11IndependentAuditError(f"{label} must be a list")
    return value


def _relative_path(value: object, *, label: str) -> str:
    _require(isinstance(value, str) and bool(value), f"{label} is invalid")
    raw = str(value)
    pure = PurePosixPath(raw)
    _require(
        "\\" not in raw
        and not pure.is_absolute()
        and ".." not in pure.parts
        and pure.as_posix() == raw
        and raw not in {".", ""},
        f"{label} is not a normalized repository path: {raw}",
    )
    return raw


def _path_list(
    payload: Mapping[str, object],
    key: str,
) -> list[str]:
    values = payload.get(key)
    _require(isinstance(values, list), f"manifest field {key} is invalid")
    normalized = [
        _relative_path(value, label=f"manifest {key} item")
        for value in values
    ]
    _require(
        normalized == sorted(normalized)
        and len(normalized) == len(set(normalized)),
        f"manifest field {key} must be sorted and unique",
    )
    return normalized


def _excluded_patterns(payload: Mapping[str, object]) -> list[str]:
    values = payload.get("excluded_paths")
    _require(
        isinstance(values, list),
        "manifest field excluded_paths is invalid",
    )
    patterns: list[str] = []
    for value in values:
        _require(
            isinstance(value, str) and bool(value),
            "manifest excluded path pattern is invalid",
        )
        raw = str(value)
        normalized = raw[:-1] if raw.endswith("/") else raw
        _relative_path(
            normalized,
            label="manifest excluded path pattern",
        )
        patterns.append(raw)
    _require(
        patterns == sorted(patterns)
        and len(patterns) == len(set(patterns)),
        "manifest field excluded_paths must be sorted and unique",
    )
    return patterns


def _git(
    root: Path,
    *arguments: str,
    check: bool = True,
) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(
            ["git", *arguments],
            cwd=root,
            check=check,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise Task11IndependentAuditError(
            "git evidence is unavailable"
        ) from exc


def _git_blob(root: Path, revision: str, relative: str) -> bytes | None:
    completed = _git(
        root,
        "show",
        f"{revision}:{relative}",
        check=False,
    )
    if completed.returncode == 0:
        return completed.stdout
    return None


def _canonical_payload_hash(root: Path, paths: Sequence[str]) -> str:
    digest = sha256()
    for relative in sorted(paths):
        path = root / relative
        _require(
            not path.is_symlink(),
            f"protected path is a symlink: {relative}",
        )
        _require(path.is_file(), f"protected path is missing: {relative}")
        encoded_path = relative.encode("utf-8")
        content = path.read_bytes()
        digest.update(str(len(encoded_path)).encode("ascii"))
        digest.update(b":")
        digest.update(encoded_path)
        digest.update(str(len(content)).encode("ascii"))
        digest.update(b":")
        digest.update(content)
    return digest.hexdigest()


def _excluded(relative: str, patterns: Sequence[str]) -> bool:
    for pattern in patterns:
        if pattern.endswith("/") and (
            relative == pattern.rstrip("/") or relative.startswith(pattern)
        ):
            return True
        if fnmatch.fnmatchcase(relative, pattern):
            return True
    return False


def _changed_paths(root: Path, revision: str) -> set[str]:
    tracked = _git(
        root,
        "diff",
        "--name-only",
        "-z",
        revision,
        "--",
    ).stdout
    untracked = _git(
        root,
        "ls-files",
        "--others",
        "--exclude-standard",
        "-z",
    ).stdout
    paths: set[str] = set()
    for raw in (tracked + untracked).split(b"\0"):
        if not raw:
            continue
        try:
            decoded = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise Task11IndependentAuditError(
                "git changed path is not UTF-8"
            ) from exc
        paths.add(_relative_path(decoded, label="git changed path"))
    return paths


def _production_diff_hash(
    *,
    root: Path,
    revision: str,
    change_paths: Sequence[str],
) -> str:
    digest = sha256()
    for relative in sorted(change_paths):
        base = _git_blob(root, revision, relative)
        current_path = root / relative
        current = current_path.read_bytes() if current_path.is_file() else None
        _require(
            not current_path.is_symlink(),
            f"changed path is a symlink: {relative}",
        )
        if base is None and current is not None:
            status = b"A"
        elif base is not None and current is None:
            status = b"D"
        elif base is not None and current is not None and base != current:
            status = b"M"
        else:
            raise Task11IndependentAuditError(
                f"manifest change path has no production diff: {relative}"
            )
        encoded = relative.encode("utf-8")
        digest.update(str(len(encoded)).encode("ascii"))
        digest.update(b":")
        digest.update(encoded)
        digest.update(status)
        for content in (base, current):
            if content is None:
                digest.update(b"-1:")
            else:
                digest.update(str(len(content)).encode("ascii"))
                digest.update(b":")
                digest.update(content)
    return digest.hexdigest()


def _validate_manifest(
    *,
    root: Path,
    path: Path,
    payload: Mapping[str, object],
) -> tuple[str, str]:
    _require(
        payload.get("schema_version") == MANIFEST_SCHEMA,
        "candidate manifest schema is invalid",
    )
    _require(
        payload.get("plan_revision") == PLAN_REVISION,
        "candidate manifest plan revision is invalid",
    )
    candidate_head = payload.get("candidate_head")
    _require(
        isinstance(candidate_head, str)
        and HEX_40.fullmatch(candidate_head) is not None,
        "candidate manifest head is invalid",
    )
    actual_head = _git(root, "rev-parse", "HEAD").stdout.decode().strip()
    _require(
        candidate_head == actual_head,
        "candidate manifest head does not match repository HEAD",
    )

    categories = {
        key: _path_list(payload, key) for key in MANIFEST_CATEGORIES
    }
    flattened = [
        relative
        for key in MANIFEST_CATEGORIES
        for relative in categories[key]
    ]
    _require(
        len(flattened) == len(set(flattened)),
        "candidate manifest typed path categories overlap",
    )
    protected = _path_list(payload, "protected_paths")
    _require(
        protected == sorted(flattened),
        "candidate manifest protected paths are not the exact typed union",
    )
    deleted = _path_list(payload, "deleted_paths")
    _require(
        set(protected).isdisjoint(deleted),
        "candidate manifest deleted paths overlap protected paths",
    )
    change_paths = _path_list(payload, "change_paths")
    _require(
        change_paths == sorted([*protected, *deleted]),
        "candidate manifest change paths are not exact",
    )
    mutable = _path_list(payload, "mutable_evidence_paths")
    _require(
        len(mutable) == 1
        and PurePosixPath(mutable[0]).name == "smoke-attempt-ledger.json",
        "candidate manifest mutable evidence paths are invalid",
    )
    excluded = _excluded_patterns(payload)

    deleted_hashes = payload.get("deleted_base_blob_sha256_by_path")
    _require(
        isinstance(deleted_hashes, dict)
        and set(deleted_hashes) == set(deleted),
        "candidate manifest deleted blob hashes are invalid",
    )
    for relative in deleted:
        _require(
            not (root / relative).exists()
            and not (root / relative).is_symlink(),
            f"deleted path still exists: {relative}",
        )
        base = _git_blob(root, candidate_head, relative)
        _require(base is not None, f"deleted base blob is missing: {relative}")
        _require(
            deleted_hashes.get(relative) == sha256(base).hexdigest(),
            f"deleted base blob hash mismatch: {relative}",
        )

    current_payload_hash = _canonical_payload_hash(root, protected)
    _require(
        payload.get("candidate_payload_sha256") == current_payload_hash
        and payload.get("protected_payload_sha256")
        == current_payload_hash,
        "candidate manifest protected payload hash mismatch",
    )

    changed = _changed_paths(root, candidate_head)
    relevant_changed = {
        relative
        for relative in changed
        if relative.startswith(RELEVANT_PREFIXES)
        and relative not in mutable
        and not _excluded(relative, excluded)
    }
    _require(
        relevant_changed == set(change_paths),
        "candidate manifest does not match the production diff",
    )
    diff_hash = _production_diff_hash(
        root=root,
        revision=candidate_head,
        change_paths=change_paths,
    )
    _require(
        path.parent.name.startswith("repair-epoch-"),
        "candidate manifest is not epoch-owned",
    )
    return current_payload_hash, diff_hash


def _validate_semantic_summary(payload: Mapping[str, object]) -> None:
    label = "semantic summary"
    _require(
        payload.get("schema_version")
        == "guide-task11-semantic-summary-v1",
        f"{label} schema is invalid",
    )
    _require(
        payload.get("matrix_kind") == "expected_contract"
        and payload.get("passed") is True,
        f"{label} is not a passing expected contract",
    )
    _require(
        _required_int(payload, "case_count", label=label) == 128,
        f"{label} must contain 128 cases",
    )
    for key in ("fit_count", "explore_count", "image_fit_count"):
        _require(
            _required_int(payload, key, label=label) > 0,
            f"{label} field {key} must be positive",
        )
    _required_zero(
        payload,
        "recommendation_outcome_contract_gap_count",
        label=label,
    )
    _required_zero(payload, "cross_parent_basis_count", label=label)


def _validate_network_report(
    payload: Mapping[str, object],
    *,
    runtime: bool,
    candidate_manifest_hash: str | None = None,
) -> str | None:
    label = "runtime network report" if runtime else "network report"
    expected_schema = (
        "guide-zero-api-runtime-network-report-v1"
        if runtime
        else "guide-zero-api-network-report-v1"
    )
    _require(
        payload.get("schema_version") == expected_schema,
        f"{label} schema is invalid",
    )
    _require(
        payload.get("guard_active") is True
        and payload.get("passed") is True,
        f"{label} is not passing under an active guard",
    )
    _required_zero(payload, "provider_call_count", label=label)
    _required_zero(payload, "outbound_network_attempt_count", label=label)
    _require(payload.get("attempts") == [], f"{label} attempts are not empty")
    if not runtime:
        return None
    _require(
        payload.get("runtime_started") is True
        and payload.get("ready_identity_written") is True
        and payload.get("shutdown_finalized") is True,
        "runtime network report lifecycle is incomplete",
    )
    _required_zero(payload, "process_creation_attempt_count", label=label)
    _required_zero(
        payload,
        "runtime_process_tree_non_loopback_attempt_count",
        label=label,
    )
    _require(
        payload.get("process_creation_attempts") == [],
        "runtime network report process attempts are not empty",
    )
    _require(
        candidate_manifest_hash is not None
        and payload.get("candidate_manifest_sha256")
        == candidate_manifest_hash,
        "runtime network report manifest hash mismatch",
    )
    runtime_identity_hash = payload.get("runtime_identity_sha256")
    _require(
        _is_digest(runtime_identity_hash),
        "runtime network report identity hash is invalid",
    )
    return str(runtime_identity_hash)


def _validate_zero_api_summary(
    payload: Mapping[str, object],
    *,
    manifest_path: Path,
    protected_payload_hash: str,
    network_path: Path,
) -> None:
    label = "zero API summary"
    _require(
        payload.get("schema_version")
        == "guide-task11-zero-api-summary-v1",
        f"{label} schema is invalid",
    )
    _require(
        payload.get("passed") is True
        and payload.get("guard_active") is True,
        f"{label} is not passing under an active guard",
    )
    _required_zero(payload, "provider_call_count", label=label)
    _required_zero(payload, "outbound_network_attempt_count", label=label)
    _require(
        payload.get("candidate_manifest_sha256")
        == _digest_file(manifest_path),
        "zero API summary manifest hash mismatch",
    )
    _require(
        payload.get("protected_payload_sha256") == protected_payload_hash,
        "zero API summary protected payload hash mismatch",
    )
    _require(
        payload.get("network_report_sha256") == _digest_file(network_path),
        "zero API summary network report hash mismatch",
    )
    commands = payload.get("commands")
    _require(
        isinstance(commands, list) and bool(commands),
        "zero API summary commands are missing",
    )
    for command in commands:
        _require(
            isinstance(command, dict)
            and command.get("returncode") == 0
            and isinstance(command.get("argv"), list)
            and bool(command["argv"])
            and all(isinstance(item, str) and item for item in command["argv"]),
            "zero API summary command evidence is invalid",
        )


def _validate_architecture(
    payload: Mapping[str, object],
    *,
    manifest: Mapping[str, object],
    protected_payload_hash: str,
) -> None:
    label = "single-path architecture"
    modules = payload.get("inspected_modules")
    violations = payload.get("violations")
    _require(
        payload.get("schema_version")
        == "guide-task11-single-path-architecture-v1",
        f"{label} schema is invalid",
    )
    _require(payload.get("passed") is True, f"{label} did not pass")
    _require(
        isinstance(modules, list)
        and bool(modules)
        and len(modules) == len(set(modules))
        and all(isinstance(item, str) and item for item in modules),
        f"{label} inspected module inventory is invalid",
    )
    _require(
        _required_int(payload, "inspected_module_count", label=label)
        == len(modules),
        f"{label} inspected module count is inconsistent",
    )
    _require(
        violations == []
        and _required_int(payload, "violation_count", label=label) == 0,
        f"{label} contains violations",
    )
    if "forbidden_symbol_count" in payload:
        _required_zero(payload, "forbidden_symbol_count", label=label)
    if "protected_payload_sha256" in payload:
        _require(
            payload.get("protected_payload_sha256")
            == protected_payload_hash,
            f"{label} protected payload hash mismatch",
        )
    source_paths = manifest.get("source_paths")
    _require(isinstance(source_paths, list), "manifest source paths are invalid")
    expected_modules = {
        str(path)[:-3].replace("/", ".")
        for path in source_paths
        if isinstance(path, str)
        and path.startswith("app/")
        and path.endswith(".py")
        and not path.endswith("/__init__.py")
    }
    _require(
        expected_modules <= set(modules),
        f"{label} omitted a protected production module",
    )


def _call_name(node: ast.Call) -> str:
    target = node.func
    if isinstance(target, ast.Name):
        return target.id
    if isinstance(target, ast.Attribute):
        parts = [target.attr]
        value = target.value
        while isinstance(value, ast.Attribute):
            parts.append(value.attr)
            value = value.value
        if isinstance(value, ast.Name):
            parts.append(value.id)
        return ".".join(reversed(parts))
    return ""


def _scan_production_architecture(root: Path) -> None:
    violations: list[str] = []
    chat_stream_roots: list[str] = []
    for path in sorted((root / "app").rglob("*.py")):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            violations.append(f"{relative}: symlinked production module")
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
        except (OSError, UnicodeError, SyntaxError) as exc:
            raise Task11IndependentAuditError(
                f"production architecture source is invalid: {relative}"
            ) from exc
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "tests" or alias.name.startswith("tests."):
                        violations.append(
                            f"{relative}:{node.lineno}: imports test seam "
                            f"{alias.name}"
                        )
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module == "tests" or module.startswith("tests."):
                    violations.append(
                        f"{relative}:{node.lineno}: imports test seam {module}"
                    )
            if isinstance(
                node,
                (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef),
            ) and node.name in BRIDGE_SYMBOLS:
                violations.append(
                    f"{relative}:{node.lineno}: forbidden capability "
                    f"{node.name}"
                )
            if isinstance(node, (ast.Name, ast.Attribute)):
                name = node.id if isinstance(node, ast.Name) else node.attr
                if name in LEGACY_FLAG_NAMES:
                    violations.append(
                        f"{relative}:{node.lineno}: legacy route flag {name}"
                    )
            if isinstance(node, ast.Call):
                call_name = _call_name(node)
                if (
                    call_name.rsplit(".", 1)[-1] in {"get", "post", "route"}
                    and node.args
                    and isinstance(node.args[0], ast.Constant)
                    and node.args[0].value == "/api/v1/chat/stream"
                ):
                    chat_stream_roots.append(
                        f"{relative}:{getattr(node, 'lineno', 0)}"
                    )
                if (
                    call_name.rsplit(".", 1)[-1] in {"get", "post", "route"}
                    and node.args
                    and isinstance(node.args[0], ast.Constant)
                    and node.args[0].value == "/api/v1/chat/message"
                ):
                    violations.append(
                        f"{relative}:{node.lineno}: alternate chat endpoint"
                    )
        for function in (
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        ):
            calls = sorted(
                (
                    item
                    for item in ast.walk(function)
                    if isinstance(item, ast.Call)
                ),
                key=lambda item: (item.lineno, item.col_offset),
            )
            save_lines = [
                item.lineno
                for item in calls
                if _call_name(item).rsplit(".", 1)[-1] == "save"
            ]
            if not save_lines:
                continue
            first_save = min(save_lines)
            for call in calls:
                terminal = _call_name(call).rsplit(".", 1)[-1].lower()
                if call.lineno > first_save and any(
                    token in terminal
                    for token in (
                        "dump",
                        "encode",
                        "materialize",
                        "project",
                        "serialize",
                    )
                ):
                    violations.append(
                        f"{relative}:{call.lineno}: post-CAS encoder "
                        f"{_call_name(call)}"
                    )
    if len(chat_stream_roots) > 1:
        violations.append(
            "multiple production chat stream roots: "
            + ", ".join(chat_stream_roots)
        )
    if violations:
        raise Task11IndependentAuditError(
            "production bridge detected: " + "; ".join(violations[:8])
        )


def _validate_test_path(
    payload: Mapping[str, object],
    *,
    manifest: Mapping[str, object],
) -> None:
    label = "test-path audit"
    _require(
        payload.get("schema_version")
        == "guide-task11-test-path-audit-v1",
        f"{label} schema is invalid",
    )
    _require(payload.get("passed") is True, f"{label} did not pass")
    _required_zero(
        payload,
        "invalid_production_path_claim_count",
        label=label,
    )
    _required_zero(
        payload,
        "unprotected_fixture_dependency_count",
        label=label,
    )
    gates = payload.get("gates")
    _require(isinstance(gates, list) and bool(gates), f"{label} gates missing")
    fixture_paths = set(manifest.get("fixture_paths", ()))
    test_paths = set(manifest.get("test_paths", ()))
    fixture_union: set[str] = set()
    production_gates: list[Mapping[str, object]] = []
    allowed_scopes = {
        "unit",
        "layer_contract",
        "frontend_fixture",
        "production_path_from_turn_meaning",
    }
    for gate in gates:
        _require(isinstance(gate, dict), f"{label} gate is invalid")
        scope = gate.get("claimed_scope")
        _require(scope in allowed_scopes, f"{label} scope is invalid")
        gate_tests = gate.get("test_files")
        gate_fixtures = gate.get("fixture_files")
        _require(
            isinstance(gate_tests, list)
            and bool(gate_tests)
            and all(item in test_paths for item in gate_tests),
            f"{label} gate test files are not protected",
        )
        _require(
            isinstance(gate_fixtures, list)
            and all(item in fixture_paths for item in gate_fixtures),
            f"{label} gate fixture files are not protected",
        )
        fixture_union.update(str(item) for item in gate_fixtures)
        if scope == "production_path_from_turn_meaning":
            production_gates.append(gate)
    _require(
        len(production_gates) == 1
        and _required_int(
            payload,
            "production_path_gate_count",
            label=label,
        )
        == 1,
        f"{label} must contain one authorizing production gate",
    )
    gate = production_gates[0]
    layers = gate.get("layers_executed")
    _require(
        gate.get("real_entrypoint") == "/api/v1/chat/stream"
        and gate.get("layers_bypassed") == []
        and gate.get("semantic_injection_type")
        in {"turn_meaning_provider", "frozen_turn_meaning_provider"}
        and isinstance(layers, list)
        and {"compiler", "router", "processor", "reducer", "sse"}
        <= set(layers)
        and bool({"sqlite", "state", "state_store"} & set(layers)),
        f"{label} production scope or executed layers are invalid",
    )
    expected_counts = {
        "case_count": 176,
        "trajectory_count": 12,
        "turn_count": 176,
        "state_edge_count": 40,
    }
    for key, expected in expected_counts.items():
        _require(
            _required_int(gate, key, label=label) == expected,
            f"{label} production gate field {key} is invalid",
        )
    dependencies = payload.get("fixture_dependencies")
    _require(
        isinstance(dependencies, list)
        and dependencies == sorted(fixture_union),
        f"{label} fixture dependency inventory is invalid",
    )


def _trace_digest(
    trace: Mapping[str, object],
    names: Sequence[str],
    *,
    label: str,
) -> str:
    for name in names:
        if name in trace:
            value = trace[name]
            _require(_is_digest(value), f"{label} field {name} is invalid")
            return str(value)
    raise Task11IndependentAuditError(
        f"{label} is missing digest field {names[0]}"
    )


def _validate_trace(trace: object, *, index: int) -> set[str]:
    label = f"production trace {index}"
    _require(isinstance(trace, dict), f"{label} is invalid")
    turn_id = trace.get("turn_id")
    trajectory_id = trace.get("trajectory_id")
    partition = trace.get("partition")
    _require(
        isinstance(turn_id, str)
        and bool(turn_id)
        and isinstance(trajectory_id, str)
        and bool(trajectory_id)
        and partition in {"semantic", "state", "bounded"},
        f"{label} identity is invalid",
    )
    expected_counts = {
        "translation_injection_count": 1,
        "compiler_call_count": 1,
        "router_call_count": 1,
        "execution_result_count": 1,
        "reducer_call_count": 1,
        "state_save_count": 1,
    }
    for key, expected in expected_counts.items():
        _require(
            _required_int(trace, key, label=label) == expected,
            f"{label} field {key} is invalid",
        )
    for key in TRACE_ZERO_FIELDS:
        _required_zero(trace, key, label=label)
    route_digest = _trace_digest(
        trace,
        ("route_decision_digest",),
        label=label,
    )
    selected_digest = _trace_digest(
        trace,
        (
            "selected_processor_decision_digest",
            "processor_decision_digest",
        ),
        label=label,
    )
    result_digest = _trace_digest(
        trace,
        ("result_decision_digest",),
        label=label,
    )
    sse_digest = _trace_digest(
        trace,
        ("sse_decision_digest", "emitted_decision_digest"),
        label=label,
    )
    _require(
        len({route_digest, selected_digest, result_digest, sse_digest}) == 1,
        f"{label} decision identity is inconsistent",
    )
    byte_pairs = (
        ("validated_sse_sha256", "emitted_sse_sha256"),
        ("validated_envelope_sha256", "emitted_envelope_sha256"),
        ("validated_frames_sha256", "emitted_frames_sha256"),
    )
    matched_pair = next(
        (
            pair
            for pair in byte_pairs
            if pair[0] in trace or pair[1] in trace
        ),
        None,
    )
    _require(matched_pair is not None, f"{label} emitted-byte proof is missing")
    validated_bytes = _trace_digest(trace, (matched_pair[0],), label=label)
    emitted_bytes = _trace_digest(trace, (matched_pair[1],), label=label)
    _require(
        validated_bytes == emitted_bytes,
        f"{label} emitted bytes differ from validated bytes",
    )

    selected = trace.get("selected_processor", trace.get("actual_processor"))
    counts = trace.get(
        "processor_invocation_counts",
        trace.get("processor_invocation_count_by_name"),
    )
    _require(
        isinstance(selected, str)
        and bool(selected)
        and isinstance(counts, dict)
        and bool(counts),
        f"{label} processor invocation evidence is missing",
    )
    _require(
        all(
            isinstance(name, str)
            and bool(name)
            and _is_int(count)
            and int(count) >= 0
            for name, count in counts.items()
        ),
        f"{label} processor invocation evidence is invalid",
    )
    _require(
        counts.get(selected) == 1
        and all(count == 0 for name, count in counts.items() if name != selected),
        f"{label} selected processor invocation count is invalid",
    )
    _require(
        trace.get("accepted") is True
        and trace.get("terminal_event") == "end"
        and trace.get("semantic_equivalence_passed") is True,
        f"{label} did not complete successfully",
    )
    loaded = _required_int(trace, "loaded_version", label=label)
    committed = _required_int(trace, "committed_version", label=label)
    _require(
        loaded >= 0 and committed == loaded + 1,
        f"{label} state version transition is invalid",
    )
    _require(
        trace.get("expected_state_edge") == trace.get("observed_state_edge")
        and isinstance(trace.get("expected_state_edge"), str)
        and bool(trace["expected_state_edge"]),
        f"{label} state transition is invalid",
    )
    _require(
        trace.get("bounded") is (partition == "bounded"),
        f"{label} bounded marker is invalid",
    )
    coverage = trace.get("coverage_edges")
    _require(
        isinstance(coverage, list)
        and len(coverage) == len(set(coverage))
        and all(isinstance(edge, str) and edge for edge in coverage),
        f"{label} observed coverage edges are invalid",
    )
    return set(coverage)


def _validate_production_summary(payload: Mapping[str, object]) -> None:
    label = "production-path summary"
    _require(
        payload.get("schema_version")
        == "guide-task11-production-path-summary-v1",
        f"{label} schema is invalid",
    )
    _require(payload.get("passed") is True, f"{label} did not pass")
    traces = payload.get("turn_traces")
    _require(
        isinstance(traces, list) and len(traces) == 176,
        f"{label} must contain 176 turn traces",
    )
    turn_ids: set[str] = set()
    semantic_count = 0
    stateful_count = 0
    bounded_count = 0
    stateful_trajectories: set[str] = set()
    observed_edges: set[str] = set()
    for index, trace in enumerate(traces):
        coverage = _validate_trace(trace, index=index)
        _require(isinstance(trace, dict), f"{label} trace is invalid")
        turn_id = str(trace["turn_id"])
        _require(turn_id not in turn_ids, f"{label} has duplicate turn IDs")
        turn_ids.add(turn_id)
        if trace["partition"] == "semantic":
            semantic_count += 1
        else:
            stateful_count += 1
            stateful_trajectories.add(str(trace["trajectory_id"]))
            observed_edges.update(coverage)
        if trace["partition"] == "bounded":
            bounded_count += 1
    expected_counts = {
        "expected_contract_case_count": 128,
        "actual_equivalence_case_count": semantic_count,
        "trajectory_count": len(stateful_trajectories),
        "stateful_turn_count": stateful_count,
        "turn_count": len(traces),
        "state_edge_count": 40,
        "required_state_edge_count": 40,
        "bounded_turn_count": bounded_count,
        "translation_injection_count": len(traces),
    }
    _require(
        semantic_count == 128
        and stateful_count == 48
        and len(stateful_trajectories) == 12
        and bounded_count == 9
        and len(observed_edges) >= 40,
        f"{label} derived coverage counts are invalid",
    )
    for key, expected in expected_counts.items():
        _require(
            _required_int(payload, key, label=label) == expected,
            f"{label} field {key} is inconsistent",
        )
    required_edges = payload.get("required_state_edges")
    if required_edges is not None:
        _require(
            isinstance(required_edges, list)
            and len(required_edges) == 40
            and len(required_edges) == len(set(required_edges))
            and set(required_edges) <= observed_edges,
            f"{label} required state edge inventory is invalid",
        )
    for key in SUMMARY_ZERO_FIELDS:
        _required_zero(payload, key, label=label)


def _sse_events(raw: str, *, label: str) -> list[tuple[str, dict[str, Any]]]:
    events: list[tuple[str, dict[str, Any]]] = []
    for block in raw.replace("\r\n", "\n").split("\n\n"):
        event_name: str | None = None
        data_lines: list[str] = []
        for line in block.splitlines():
            if line.startswith("event:"):
                event_name = line.removeprefix("event:").strip()
            elif line.startswith("data:"):
                data_lines.append(line.removeprefix("data:").lstrip())
        if event_name is None and not data_lines:
            continue
        _require(
            event_name is not None and bool(data_lines),
            f"{label} contains an incomplete SSE event",
        )
        try:
            data = json.loads("\n".join(data_lines))
        except json.JSONDecodeError as exc:
            raise Task11IndependentAuditError(
                f"{label} contains invalid SSE JSON"
            ) from exc
        _require(isinstance(data, dict), f"{label} SSE data is not an object")
        events.append((event_name, data))
    return events


def _artifact_index(payload: Mapping[str, object]) -> dict[str, str]:
    raw = payload.get(
        "artifact_sha256",
        payload.get("artifact_sha256_by_path"),
    )
    _require(
        isinstance(raw, dict) and bool(raw),
        "browser summary artifact hash index is missing",
    )
    result: dict[str, str] = {}
    for key, value in raw.items():
        relative = _relative_path(key, label="browser artifact path")
        _require(
            _is_digest(value),
            f"browser artifact hash is invalid: {relative}",
        )
        result[relative] = str(value)
    return result


def _validate_browser_summary(
    *,
    path: Path,
    payload: Mapping[str, object],
    viewport: str,
) -> tuple[str, str]:
    label = f"{viewport} browser summary"
    _require(
        payload.get("schema_version")
        == "guide-mainline-contract-browser-audit-v1",
        f"{label} schema is invalid",
    )
    _require(
        payload.get("trajectory_set") == "fixture"
        and payload.get("viewport") == viewport
        and payload.get("passed") is True,
        f"{label} identity or verdict is invalid",
    )
    _require(
        _required_int(payload, "turn_count", label=label) == 7,
        f"{label} turn count is invalid",
    )
    _required_zero(payload, "invalid_clarification_count", label=label)
    runtime_digest = payload.get("runtime_identity_sha256")
    challenge_digest = payload.get(
        "consumed_health_challenge_sha256",
        payload.get(
            "consumed_challenge_sha256",
            payload.get("health_challenge_sha256"),
        ),
    )
    sandbox_digest = payload.get("sandbox_audit_sha256")
    _require(
        _is_digest(runtime_digest)
        and _is_digest(challenge_digest)
        and _is_digest(sandbox_digest),
        f"{label} runtime, challenge, or sandbox digest is invalid",
    )
    _require(
        isinstance(payload.get("sandbox_identity"), str)
        and bool(payload["sandbox_identity"]),
        f"{label} sandbox identity is missing",
    )
    _require(
        _required_int(payload, "browser_request_count", label=label) >= 7,
        f"{label} browser request count is invalid",
    )
    _required_zero(
        payload,
        "process_tree_non_loopback_attempt_count",
        label=label,
    )
    _required_zero(
        payload,
        "browser_observed_non_loopback_attempt_count",
        label=label,
    )

    turns = payload.get("turns")
    _require(
        isinstance(turns, list) and len(turns) == len(FIXTURE_TURNS),
        f"{label} turn inventory is invalid",
    )
    turn_ids: list[str] = []
    for item in turns:
        _require(isinstance(item, dict), f"{label} turn item is invalid")
        turn_id = item.get("turn_id")
        directory = item.get("directory", turn_id)
        _require(
            isinstance(turn_id, str)
            and isinstance(directory, str)
            and directory == turn_id,
            f"{label} turn directory is invalid",
        )
        turn_ids.append(turn_id)
    _require(
        tuple(turn_ids) == FIXTURE_TURNS,
        f"{label} fixture turn inventory is incomplete",
    )

    root = path.parent
    expected_index: dict[str, str] = {}
    for artifact in sorted(root.rglob("*")):
        if artifact == path:
            continue
        _require(
            not artifact.is_symlink(),
            f"{label} contains a symlinked artifact",
        )
        if artifact.is_file():
            expected_index[artifact.relative_to(root).as_posix()] = (
                _digest_file(artifact)
            )
    declared_index = _artifact_index(payload)
    _require(
        declared_index == expected_index,
        f"{label} artifact hash index is stale or incomplete",
    )
    _require(
        sandbox_digest
        in {
            digest
            for relative, digest in expected_index.items()
            if "sandbox-audit" in PurePosixPath(relative).name
        },
        f"{label} sandbox audit hash is not bound to an artifact",
    )

    for turn_id in FIXTURE_TURNS:
        turn_dir = root / turn_id
        _require(turn_dir.is_dir(), f"{label} turn directory is missing")
        names = {
            item.name for item in turn_dir.iterdir() if item.is_file()
        }
        _require(
            REQUIRED_BROWSER_FILES <= names,
            f"{label} turn {turn_id} is missing evidence files",
        )
        request = _load_object(
            turn_dir / "request.json",
            label=f"{label} request",
        )
        _require(
            request.get("turn_id") == turn_id
            and isinstance(request.get("request_id"), str)
            and bool(request["request_id"]),
            f"{label} request identity is invalid",
        )
        contract = _load_object(
            turn_dir / "presentation-contract.json",
            label=f"{label} presentation contract",
        )
        events = _sse_events(
            (turn_dir / "stream.sse").read_text(encoding="utf-8"),
            label=f"{label} stream",
        )
        contracts = [
            data for event, data in events if event == "presentation_contract"
        ]
        _require(
            contracts == [contract],
            f"{label} emitted presentation bytes do not match the contract",
        )
        _require(
            any(event == "end" for event, _ in events),
            f"{label} stream has no terminal end event",
        )
        _require(
            bool((turn_dir / "screenshot.png").read_bytes()),
            f"{label} screenshot is empty",
        )
        _require(
            _load_list(
                turn_dir / "console.json",
                label=f"{label} console",
            )
            == [],
            f"{label} browser console is not empty",
        )
        _require(
            _load_list(
                turn_dir / "network.json",
                label=f"{label} browser network",
            )
            == [],
            f"{label} browser network failures are not empty",
        )
        sandbox = _load_object(
            turn_dir / "sandbox-audit.json",
            label=f"{label} sandbox audit",
        )
        _require(
            sandbox.get("passed") is True
            and sandbox.get("attempts") == []
            and sandbox.get("process_tree_non_loopback_attempt_count") == 0,
            f"{label} turn sandbox evidence failed",
        )
    return str(runtime_digest), str(challenge_digest)


def _repair_epoch(path: Path) -> int:
    match = re.fullmatch(r"repair-epoch-(\d+)", path.parent.name)
    _require(match is not None, "audit output is not epoch-owned")
    return int(match.group(1))


def _publish_exclusive(path: Path, payload: Mapping[str, object]) -> None:
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"independent audit already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = (
        json.dumps(
            payload,
            ensure_ascii=True,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.tmp-",
        dir=path.parent,
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb", closefd=True) as stream:
            stream.write(serialized)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            raise FileExistsError(
                f"independent audit already exists: {path}"
            ) from None
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def run_independent_audit(
    *,
    repo_root: str | Path,
    manifest_path: str | Path,
    semantic_summary_path: str | Path,
    zero_api_summary_path: str | Path,
    single_path_architecture_path: str | Path,
    test_path_audit_path: str | Path,
    network_report_path: str | Path,
    runtime_network_report_path: str | Path,
    production_path_summary_path: str | Path,
    desktop_summary_path: str | Path,
    mobile_summary_path: str | Path,
    output_path: str | Path,
) -> dict[str, object]:
    root = Path(repo_root).resolve()
    _require(root.is_dir(), f"repository root is missing: {root}")
    raw_output = Path(output_path)
    if raw_output.exists() or raw_output.is_symlink():
        output = raw_output.absolute()
        raise FileExistsError(f"independent audit already exists: {output}")
    output = raw_output.resolve()

    inputs = {
        "candidate_manifest": _input_file(
            manifest_path,
            label="candidate manifest",
        ),
        "semantic_summary": _input_file(
            semantic_summary_path,
            label="semantic summary",
        ),
        "zero_api_summary": _input_file(
            zero_api_summary_path,
            label="zero API summary",
        ),
        "single_path_architecture": _input_file(
            single_path_architecture_path,
            label="single-path architecture",
        ),
        "test_path_audit": _input_file(
            test_path_audit_path,
            label="test-path audit",
        ),
        "network_report": _input_file(
            network_report_path,
            label="network report",
        ),
        "runtime_network_report": _input_file(
            runtime_network_report_path,
            label="runtime network report",
        ),
        "production_path_summary": _input_file(
            production_path_summary_path,
            label="production-path summary",
        ),
        "desktop_summary": _input_file(
            desktop_summary_path,
            label="desktop summary",
        ),
        "mobile_summary": _input_file(
            mobile_summary_path,
            label="mobile summary",
        ),
    }
    _require(
        len(set(inputs.values())) == len(inputs),
        "independent audit inputs must be distinct files",
    )
    _require(
        output not in set(inputs.values()),
        "independent audit output aliases an input",
    )
    epoch_root = inputs["candidate_manifest"].parent
    _require(
        output.parent == epoch_root
        and all(
            path.parent == epoch_root
            for role, path in inputs.items()
            if role
            not in {
                "desktop_summary",
                "mobile_summary",
                "candidate_manifest",
            }
        )
        and inputs["desktop_summary"].parent.parent == epoch_root
        and inputs["mobile_summary"].parent.parent == epoch_root,
        "independent audit inputs do not belong to one repair epoch",
    )
    manifest = _load_object(
        inputs["candidate_manifest"],
        label="candidate manifest",
    )
    protected_payload_hash, diff_hash = _validate_manifest(
        root=root,
        path=inputs["candidate_manifest"],
        payload=manifest,
    )
    evidence = {
        role: _load_object(path, label=role.replace("_", " "))
        for role, path in inputs.items()
        if role != "candidate_manifest"
    }

    _validate_semantic_summary(evidence["semantic_summary"])
    _validate_network_report(evidence["network_report"], runtime=False)
    runtime_identity_hash = _validate_network_report(
        evidence["runtime_network_report"],
        runtime=True,
        candidate_manifest_hash=_digest_file(inputs["candidate_manifest"]),
    )
    _validate_zero_api_summary(
        evidence["zero_api_summary"],
        manifest_path=inputs["candidate_manifest"],
        protected_payload_hash=protected_payload_hash,
        network_path=inputs["network_report"],
    )
    _validate_architecture(
        evidence["single_path_architecture"],
        manifest=manifest,
        protected_payload_hash=protected_payload_hash,
    )
    _scan_production_architecture(root)
    _validate_test_path(
        evidence["test_path_audit"],
        manifest=manifest,
    )
    _validate_production_summary(evidence["production_path_summary"])
    desktop_runtime, desktop_challenge = _validate_browser_summary(
        path=inputs["desktop_summary"],
        payload=evidence["desktop_summary"],
        viewport="desktop",
    )
    mobile_runtime, mobile_challenge = _validate_browser_summary(
        path=inputs["mobile_summary"],
        payload=evidence["mobile_summary"],
        viewport="mobile",
    )
    _require(
        desktop_runtime == mobile_runtime == runtime_identity_hash,
        "network, desktop, and mobile evidence used different runtime "
        "identities",
    )
    _require(
        desktop_challenge != mobile_challenge,
        "desktop and mobile summaries reused a health challenge",
    )

    reviewed_hashes = {
        role: _digest_file(path) for role, path in inputs.items()
    }
    report: dict[str, object] = {
        "schema_version": REPORT_SCHEMA,
        "passed": True,
        "plan_revision": PLAN_REVISION,
        "repair_epoch": _repair_epoch(output),
        "candidate_manifest_sha256": reviewed_hashes[
            "candidate_manifest"
        ],
        "protected_payload_sha256": protected_payload_hash,
        "production_diff_sha256": diff_hash,
        "reviewed_evidence_sha256": reviewed_hashes,
        "checks": {
            "manifest": True,
            "production_diff": True,
            "semantic_summary": True,
            "zero_api_summary": True,
            "single_path_architecture": True,
            "production_bridge_scan": True,
            "test_path_audit": True,
            "network_report": True,
            "runtime_network_report": True,
            "production_path_summary": True,
            "desktop_summary": True,
            "mobile_summary": True,
        },
        "finding_count": 0,
        "p0_finding_count": 0,
        "p1_finding_count": 0,
        "findings": [],
    }
    _publish_exclusive(output, report)
    return report


run_task11_independent_audit = run_independent_audit


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--semantic-summary", type=Path, required=True)
    parser.add_argument("--zero-api-summary", type=Path, required=True)
    parser.add_argument(
        "--single-path-architecture",
        type=Path,
        required=True,
    )
    parser.add_argument("--test-path-audit", type=Path, required=True)
    parser.add_argument("--network-report", type=Path, required=True)
    parser.add_argument(
        "--runtime-network-report",
        type=Path,
        required=True,
    )
    parser.add_argument(
        "--production-path-summary",
        type=Path,
        required=True,
    )
    parser.add_argument("--desktop-summary", type=Path, required=True)
    parser.add_argument("--mobile-summary", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    report = run_independent_audit(
        repo_root=args.repo_root,
        manifest_path=args.manifest,
        semantic_summary_path=args.semantic_summary,
        zero_api_summary_path=args.zero_api_summary,
        single_path_architecture_path=args.single_path_architecture,
        test_path_audit_path=args.test_path_audit,
        network_report_path=args.network_report,
        runtime_network_report_path=args.runtime_network_report,
        production_path_summary_path=args.production_path_summary,
        desktop_summary_path=args.desktop_summary,
        mobile_summary_path=args.mobile_summary,
        output_path=args.output,
    )
    print(json.dumps(report, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "REPORT_SCHEMA",
    "Task11IndependentAuditError",
    "run_independent_audit",
    "run_task11_independent_audit",
]
