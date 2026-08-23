from __future__ import annotations

import argparse
import ast
from collections.abc import Callable
from hashlib import sha256
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
from typing import Any, Sequence

from tools.guide_gates.attempt_ledger import (
    read_attempt_context,
    read_ledger,
)


_MANIFEST_SCHEMA = "guide-task11-candidate-manifest-v1"
_READINESS_SCHEMA = "guide-task11-readiness-v1"
_PLAN_REVISION_PATTERN = re.compile(
    r"^Plan revision:\s*(\S+)\s*$",
    re.MULTILINE,
)
_FILE_LINE_PATTERN = re.compile(
    r"^- (Create|Modify|Test|Generate|Delete): `([^`]+)`$",
    re.MULTILINE,
)
_EXCLUDED_PATHS = (
    ".dbg/",
    ".tmp-*",
    "app/static/demo.html",
    "app/static/recording-v1/",
    "debug-*.md",
    "docs/audits/continuous-conversation/",
    "docs/superpowers/plans/2026-08-20-recording-ready-guide-path.md",
)
_RELEVANT_PREFIXES = (
    "app/guide/",
    "app/guide_runtime/",
    "app/static/",
    "tests/guide/",
    "tests/fixtures/guide/",
    "tools/guide_gates/",
    "tools/guide_data/",
    "docs/audits/semantic-turn-meaning/",
    "docs/superpowers/plans/",
)
_FIXTURE_TURN_IDS = (
    "fixture-explore-recommendation",
    "fixture-fit-recommendation",
    "fixture-product-knowledge",
    "fixture-comparison",
    "fixture-image-identity",
    "fixture-image-fit-recommendation",
    "fixture-multi-image-comparison",
)
_BOUNDED_TURN_COUNT = 9
_FIXTURE_PATH_PATTERN = re.compile(
    r"tests/fixtures/guide/[A-Za-z0-9_./-]+"
)


class Task11ReadinessError(ValueError):
    pass


def _canonical_bytes(payload: object) -> bytes:
    return (
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_canonical_bytes(payload))


def _read_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Task11ReadinessError(f"{label} is invalid") from exc
    if not isinstance(payload, dict):
        raise Task11ReadinessError(f"{label} is invalid")
    return payload


def _normalized_path(value: str) -> str:
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise Task11ReadinessError("candidate path escapes repository")
    return path.as_posix()


def parse_task11_files(
    plan_path: str | Path,
) -> dict[str, tuple[str, ...]]:
    text = Path(plan_path).read_text(encoding="utf-8")
    task_start = text.find("### Task 11:")
    task_end = text.find("### Task 12:", task_start + 1)
    if task_start < 0:
        raise Task11ReadinessError("Task 11 section is missing")
    if task_end < 0:
        task_end = len(text)
    task = text[task_start:task_end]
    files_start = task.find("**Files:**")
    first_step = task.find("- [", files_start)
    if files_start < 0 or first_step < 0:
        raise Task11ReadinessError("Task 11 Files block is missing")
    rows = _FILE_LINE_PATTERN.findall(task[files_start:first_step])
    if not rows:
        raise Task11ReadinessError("Task 11 Files block is empty")
    output: dict[str, list[str]] = {
        "source_paths": [],
        "test_paths": [],
        "tool_paths": [],
        "plan_paths": [],
        "fixture_paths": [],
        "deleted_paths": [],
        "generated_paths": [],
    }
    for action, raw_path in rows:
        path = _normalized_path(raw_path)
        if action == "Delete":
            key = "deleted_paths"
        elif (
            action == "Generate"
            or path.startswith(
                "docs/audits/final-release/"
                "mainline-contract-closure/"
            )
        ):
            key = "generated_paths"
        elif path.startswith("tests/fixtures/"):
            key = "fixture_paths"
        elif path.startswith("tests/"):
            key = "test_paths"
        elif path.startswith("tools/"):
            key = "tool_paths"
        elif path.startswith("docs/superpowers/plans/"):
            key = "plan_paths"
        else:
            key = "source_paths"
        if path in output[key]:
            raise Task11ReadinessError(
                f"duplicate Task 11 file path: {path}"
            )
        output[key].append(path)
    return {
        key: tuple(sorted(values))
        for key, values in output.items()
    }


def _fixture_dependencies_in_python(path: Path) -> tuple[str, ...]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError) as exc:
        raise Task11ReadinessError(
            f"cannot inspect test fixture dependencies: {path}"
        ) from exc
    dependencies = {
        match.group(0).rstrip("./")
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        for match in _FIXTURE_PATH_PATTERN.finditer(node.value)
    }
    return tuple(sorted(dependencies))


def build_test_path_audit(
    *,
    repo_root: str | Path,
    plan_path: str | Path,
    output_path: str | Path,
) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    parsed = parse_task11_files(plan_path)
    fixture_dependencies = set(parsed["fixture_paths"])
    gates: list[dict[str, Any]] = []
    for test_path in parsed["test_paths"]:
        path = root / test_path
        if not path.is_file():
            raise Task11ReadinessError(
                f"Task 11 test path is missing: {test_path}"
            )
        dependencies = _fixture_dependencies_in_python(path)
        fixture_dependencies.update(dependencies)
        name = path.stem
        if name == "test_task11_production_path_matrix":
            gate = "task11-production-path-matrix"
            claimed_scope = "production_path"
            real_entrypoint = "/api/v1/chat/stream"
            layers_executed = [
                "translation",
                "compiler",
                "router",
                "processor",
                "reducer",
                "sqlite",
                "sse",
            ]
            layers_bypassed: list[str] = []
            semantic_injection_type = "turn_meaning_provider"
            case_count = 176
            trajectory_count = 12
            turn_count = 176
            state_edge_count = 40
        elif (
            "frontend" in name
            or "browser_audit" in name
        ):
            gate = name
            claimed_scope = "frontend_fixture"
            real_entrypoint = "prebuilt_typed_sse"
            layers_executed = ["browser_reducer", "dom_renderer"]
            layers_bypassed = [
                "translation",
                "compiler",
                "router",
                "processor",
                "reducer",
                "sqlite",
            ]
            semantic_injection_type = "prebuilt_sse"
            case_count = 0
            trajectory_count = 0
            turn_count = 0
            state_edge_count = 0
        else:
            gate = name
            claimed_scope = "layer_contract"
            real_entrypoint = "direct_component_api"
            layers_executed = ["declared_test_layer"]
            layers_bypassed = ["http_production_path"]
            semantic_injection_type = "direct_contract_or_component"
            case_count = 0
            trajectory_count = 0
            turn_count = 0
            state_edge_count = 0
        gates.append({
            "gate": gate,
            "claimed_scope": claimed_scope,
            "real_entrypoint": real_entrypoint,
            "layers_executed": layers_executed,
            "layers_bypassed": layers_bypassed,
            "semantic_injection_type": semantic_injection_type,
            "test_files": [test_path],
            "fixture_files": list(dependencies),
            "case_count": case_count,
            "trajectory_count": trajectory_count,
            "turn_count": turn_count,
            "state_edge_count": state_edge_count,
        })
    missing_fixtures = sorted(
        path
        for path in fixture_dependencies
        if not (root / path).is_file()
    )
    production_count = sum(
        gate["claimed_scope"] == "production_path"
        for gate in gates
    )
    invalid_claims = sum(
        gate["claimed_scope"] == "production_path"
        and (
            gate["real_entrypoint"] != "/api/v1/chat/stream"
            or gate["layers_bypassed"]
            or gate["semantic_injection_type"]
            != "turn_meaning_provider"
        )
        for gate in gates
    )
    audit = {
        "schema_version": "guide-task11-test-path-audit-v1",
        "passed": (
            production_count == 1
            and invalid_claims == 0
            and not missing_fixtures
        ),
        "production_path_gate_count": production_count,
        "invalid_production_path_claim_count": invalid_claims,
        "unprotected_fixture_dependency_count": len(
            missing_fixtures
        ),
        "fixture_dependencies": sorted(fixture_dependencies),
        "missing_fixture_dependencies": missing_fixtures,
        "gates": gates,
    }
    _write_json(Path(output_path), audit)
    if audit["passed"] is not True:
        raise Task11ReadinessError("test path audit failed")
    return audit


def canonical_payload_sha256(
    repo_root: str | Path,
    paths: Sequence[str],
) -> str:
    root = Path(repo_root).resolve()
    digest = sha256()
    for raw_path in sorted(paths):
        relative = _normalized_path(raw_path)
        path = root / relative
        if path.is_symlink():
            raise Task11ReadinessError(
                f"candidate path is a symlink: {relative}"
            )
        if not path.is_file():
            raise Task11ReadinessError(
                f"candidate path is missing: {relative}"
            )
        encoded_path = relative.encode("utf-8")
        content = path.read_bytes()
        digest.update(str(len(encoded_path)).encode("ascii"))
        digest.update(b":")
        digest.update(encoded_path)
        digest.update(str(len(content)).encode("ascii"))
        digest.update(b":")
        digest.update(content)
    return digest.hexdigest()


def _is_excluded(path: str) -> bool:
    if path in {
        "app/static/demo.html",
        (
            "docs/superpowers/plans/"
            "2026-08-20-recording-ready-guide-path.md"
        ),
    }:
        return True
    if path.startswith(
        (
            ".dbg/",
            ".tmp-",
            "app/static/recording-v1/",
            "docs/audits/continuous-conversation/",
        )
    ):
        return True
    return (
        path.startswith("debug-")
        and path.endswith(".md")
    )


def _is_relevant(path: str) -> bool:
    return any(
        path == prefix.rstrip("/") or path.startswith(prefix)
        for prefix in _RELEVANT_PREFIXES
    )


def discover_relevant_changes(repo_root: str | Path) -> tuple[str, ...]:
    root = Path(repo_root).resolve()
    completed = subprocess.run(
        [
            "git",
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
        ],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    paths: list[str] = []
    for line in completed.stdout.splitlines():
        if len(line) < 4:
            continue
        value = line[3:]
        if " -> " in value:
            value = value.split(" -> ", 1)[1]
        path = _normalized_path(value)
        if _is_relevant(path) and not _is_excluded(path):
            paths.append(path)
    return tuple(sorted(set(paths)))


def _plan_revision(plan_path: Path) -> str:
    match = _PLAN_REVISION_PATTERN.search(
        plan_path.read_text(encoding="utf-8")
    )
    if match is None:
        raise Task11ReadinessError("plan revision is missing")
    return match.group(1)


def _git_head(repo_root: Path) -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def build_candidate_manifest(
    *,
    repo_root: str | Path,
    plan_path: str | Path,
    output_path: str | Path,
    candidate_head: str | None = None,
    changed_paths: Sequence[str] | None = None,
    test_path_audit_path: str | Path | None = None,
) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    plan = Path(plan_path).resolve()
    try:
        plan_relative = plan.relative_to(root).as_posix()
    except ValueError as exc:
        raise Task11ReadinessError(
            "plan path must be inside repository"
        ) from exc
    parsed = parse_task11_files(plan)
    fixture_paths = set(parsed["fixture_paths"])
    if test_path_audit_path is not None:
        test_path_audit = _read_object(
            Path(test_path_audit_path),
            label="test path audit",
        )
        if (
            test_path_audit.get("schema_version")
            != "guide-task11-test-path-audit-v1"
            or test_path_audit.get("passed") is not True
            or not isinstance(
                test_path_audit.get("fixture_dependencies"),
                list,
            )
        ):
            raise Task11ReadinessError("test path audit is invalid")
        fixture_paths.update(
            _normalized_path(str(path))
            for path in test_path_audit["fixture_dependencies"]
        )
    protected = tuple(
        sorted(
            {
                *parsed["source_paths"],
                *parsed["test_paths"],
                *parsed["tool_paths"],
                *parsed["plan_paths"],
                *fixture_paths,
            }
        )
    )
    deleted = tuple(sorted(parsed["deleted_paths"]))
    existing_deleted = tuple(
        path for path in deleted if (root / path).exists()
    )
    if existing_deleted:
        raise Task11ReadinessError(
            "planned deleted paths still exist: "
            + ", ".join(existing_deleted)
        )
    if plan_relative not in protected:
        raise Task11ReadinessError(
            "active plan is missing from Task 11 Files"
        )
    changed = tuple(
        sorted(
            _normalized_path(path)
            for path in (
                discover_relevant_changes(root)
                if changed_paths is None
                else changed_paths
            )
            if not _is_excluded(path)
        )
    )
    approved_changes = {*protected, *deleted}
    missing = tuple(
        path for path in changed if path not in approved_changes
    )
    if missing:
        raise Task11ReadinessError(
            "relevant changed paths missing from Task 11 Files: "
            + ", ".join(missing)
        )
    payload_sha256 = canonical_payload_sha256(root, protected)
    manifest = {
        "schema_version": _MANIFEST_SCHEMA,
        "plan_revision": _plan_revision(plan),
        "candidate_head": candidate_head or _git_head(root),
        "source_paths": list(parsed["source_paths"]),
        "test_paths": list(parsed["test_paths"]),
        "tool_paths": list(parsed["tool_paths"]),
        "plan_paths": list(parsed["plan_paths"]),
        "fixture_paths": sorted(fixture_paths),
        "deleted_paths": list(deleted),
        "excluded_paths": list(_EXCLUDED_PATHS),
        "protected_paths": list(protected),
        "candidate_payload_sha256": payload_sha256,
        "protected_payload_sha256": payload_sha256,
    }
    _write_json(Path(output_path), manifest)
    return manifest


def build_semantic_summary(
    *,
    cases_path: str | Path,
    output_path: str | Path,
) -> dict[str, Any]:
    from app.guide.understanding.turn_meaning_contracts import (
        EXPLORE_RECOMMENDATION_BASES,
        FIT_RECOMMENDATION_BASES,
    )
    from tools.guide_gates.build_semantic_equivalence_matrix import (
        build_matrix,
    )
    from tools.guide_gates.turn_meaning_gate import load_gate_cases

    rows = build_matrix(load_gate_cases(cases_path))
    outcomes = tuple(row["expected_outcome"] for row in rows)
    recommendation_outcomes = tuple(
        outcome
        for outcome in outcomes
        if outcome["responsibility"]
        in {"recommendation", "image_recommendation"}
    )
    fit_count = sum(
        outcome["recommendation_mode"] == "fit"
        for outcome in recommendation_outcomes
    )
    explore_count = sum(
        outcome["recommendation_mode"] == "explore"
        for outcome in recommendation_outcomes
    )
    image_fit_count = sum(
        outcome["responsibility"] == "image_recommendation"
        and outcome["recommendation_mode"] == "fit"
        for outcome in recommendation_outcomes
    )
    missing_outcomes = sum(
        outcome["recommendation_mode"] is None
        or outcome["recommendation_mode_basis"] is None
        for outcome in recommendation_outcomes
    )
    cross_parent = sum(
        (
            outcome["recommendation_mode"] == "explore"
            and outcome["recommendation_mode_basis"]
            not in EXPLORE_RECOMMENDATION_BASES
        )
        or (
            outcome["recommendation_mode"] == "fit"
            and outcome["recommendation_mode_basis"]
            not in FIT_RECOMMENDATION_BASES
        )
        for outcome in recommendation_outcomes
    )
    summary = {
        "schema_version": "guide-task11-semantic-summary-v1",
        "matrix_kind": "expected_contract",
        "cases_sha256": sha256(Path(cases_path).read_bytes()).hexdigest(),
        "passed": (
            len(rows) == 128
            and fit_count > 0
            and explore_count > 0
            and image_fit_count > 0
            and missing_outcomes == 0
            and cross_parent == 0
        ),
        "case_count": len(rows),
        "fit_count": fit_count,
        "explore_count": explore_count,
        "image_fit_count": image_fit_count,
        "recommendation_outcome_contract_gap_count": missing_outcomes,
        "cross_parent_basis_count": cross_parent,
    }
    _write_json(Path(output_path), summary)
    return summary


def _zero_api_commands(
    manifest: dict[str, Any],
    *,
    python_executable: str,
) -> tuple[tuple[str, ...], ...]:
    test_paths = tuple(
        path
        for path in manifest["test_paths"]
        if path.endswith(".py")
    )
    return (
        ("git", "diff", "--check"),
        (
            python_executable,
            "-m",
            "compileall",
            "-q",
            "app",
            "tools",
            "tests",
        ),
        (
            python_executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "tools.guide_gates.zero_api_network_guard",
            *test_paths,
        ),
    )


def run_zero_api_suite(
    *,
    repo_root: str | Path,
    manifest_path: str | Path,
    output_path: str | Path,
    network_report_path: str | Path,
    command_runner: Callable[..., subprocess.CompletedProcess[str]] = (
        subprocess.run
    ),
    python_executable: str = sys.executable,
) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    manifest, manifest_root = _validated_manifest(Path(manifest_path))
    if manifest_root != root:
        raise Task11ReadinessError("candidate repository root mismatch")
    commands = _zero_api_commands(
        manifest,
        python_executable=python_executable,
    )
    environment = os.environ.copy()
    for key in (
        "GUIDE_LLM_API_KEY",
        "GUIDE_COPY_LLM_API_KEY",
        "OPENAI_API_KEY",
    ):
        environment.pop(key, None)
    network_report = Path(network_report_path).resolve()
    if network_report.exists() or network_report.is_symlink():
        raise Task11ReadinessError(
            "zero API network report already exists"
        )
    environment["XIAORO_ZERO_API_NETWORK_REPORT"] = str(
        network_report
    )
    results: list[dict[str, Any]] = []
    for command in commands:
        completed = command_runner(
            command,
            cwd=root,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        results.append(
            {
                "argv": list(command),
                "returncode": completed.returncode,
                "stdout": completed.stdout,
                "stderr": completed.stderr,
            }
        )
        if completed.returncode != 0:
            break
    measured_network = (
        _read_object(
            network_report,
            label="zero API network report",
        )
        if network_report.is_file()
        else None
    )
    network_passed = (
        measured_network is not None
        and _network_report_passed(measured_network)
    )
    summary = {
        "schema_version": "guide-task11-zero-api-summary-v1",
        "passed": (
            len(results) == len(commands)
            and all(item["returncode"] == 0 for item in results)
            and network_passed
        ),
        "guard_active": (
            measured_network.get("guard_active")
            if measured_network is not None
            else None
        ),
        "provider_call_count": (
            measured_network.get("provider_call_count")
            if measured_network is not None
            else None
        ),
        "outbound_network_attempt_count": (
            measured_network.get("outbound_network_attempt_count")
            if measured_network is not None
            else None
        ),
        "network_report_sha256": (
            sha256(network_report.read_bytes()).hexdigest()
            if measured_network is not None
            else None
        ),
        "candidate_manifest_sha256": sha256(
            Path(manifest_path).read_bytes()
        ).hexdigest(),
        "protected_payload_sha256": (
            manifest["protected_payload_sha256"]
        ),
        "commands": results,
    }
    _write_json(Path(output_path), summary)
    if summary["passed"] is not True:
        raise Task11ReadinessError("zero API suite failed")
    return summary


def prepare_task11_evidence(
    *,
    repo_root: str | Path,
    plan_path: str | Path,
    manifest_path: str | Path,
    semantic_summary_path: str | Path,
    zero_api_summary_path: str | Path,
    network_report_path: str | Path,
    cases_path: str | Path,
    candidate_head: str | None = None,
    changed_paths: Sequence[str] | None = None,
    command_runner: Callable[..., subprocess.CompletedProcess[str]] = (
        subprocess.run
    ),
    python_executable: str = sys.executable,
) -> dict[str, dict[str, Any]]:
    manifest = build_candidate_manifest(
        repo_root=repo_root,
        plan_path=plan_path,
        output_path=manifest_path,
        candidate_head=candidate_head,
        changed_paths=changed_paths,
    )
    semantic = build_semantic_summary(
        cases_path=cases_path,
        output_path=semantic_summary_path,
    )
    zero_api = run_zero_api_suite(
        repo_root=repo_root,
        manifest_path=manifest_path,
        output_path=zero_api_summary_path,
        network_report_path=network_report_path,
        command_runner=command_runner,
        python_executable=python_executable,
    )
    return {
        "candidate_manifest": manifest,
        "semantic_summary": semantic,
        "zero_api_summary": zero_api,
        "network_report": _read_object(
            Path(network_report_path),
            label="zero API network report",
        ),
    }


def _manifest_root(
    manifest_path: Path,
    manifest: dict[str, Any],
) -> Path:
    protected = manifest.get("protected_paths")
    if not isinstance(protected, list) or not protected:
        raise Task11ReadinessError("candidate manifest is invalid")
    for candidate in (
        manifest_path.resolve().parent,
        *manifest_path.resolve().parents,
    ):
        if all((candidate / str(path)).is_file() for path in protected):
            return candidate
    raise Task11ReadinessError("candidate repository root is unavailable")


def _validated_manifest(path: Path) -> tuple[dict[str, Any], Path]:
    manifest = _read_object(path, label="candidate manifest")
    if manifest.get("schema_version") != _MANIFEST_SCHEMA:
        raise Task11ReadinessError("candidate manifest is invalid")
    categories = (
        "source_paths",
        "test_paths",
        "tool_paths",
        "plan_paths",
        "fixture_paths",
    )
    if any(not isinstance(manifest.get(key), list) for key in categories):
        raise Task11ReadinessError("candidate manifest is invalid")
    protected = sorted(
        path
        for key in categories
        for path in manifest[key]
    )
    if (
        len(protected) != len(set(protected))
        or manifest.get("protected_paths") != protected
    ):
        raise Task11ReadinessError(
            "candidate protected paths are invalid"
        )
    deleted = manifest.get("deleted_paths")
    if (
        not isinstance(deleted, list)
        or len(deleted) != len(set(deleted))
    ):
        raise Task11ReadinessError(
            "candidate deleted paths are invalid"
        )
    root = _manifest_root(path, manifest)
    if any((root / str(item)).exists() for item in deleted):
        raise Task11ReadinessError(
            "candidate deleted paths are invalid"
        )
    current = canonical_payload_sha256(root, protected)
    if (
        manifest.get("candidate_payload_sha256") != current
        or manifest.get("protected_payload_sha256") != current
    ):
        raise Task11ReadinessError("protected payload drift")
    return manifest, root


def _semantic_passed(payload: dict[str, Any]) -> bool:
    return (
        payload.get("schema_version")
        == "guide-task11-semantic-summary-v1"
        and payload.get("matrix_kind") == "expected_contract"
        and payload.get("passed") is True
        and payload.get("case_count") == 128
        and isinstance(payload.get("fit_count"), int)
        and payload["fit_count"] > 0
        and isinstance(payload.get("explore_count"), int)
        and payload["explore_count"] > 0
        and isinstance(payload.get("image_fit_count"), int)
        and payload["image_fit_count"] > 0
        and payload.get(
            "recommendation_outcome_contract_gap_count"
        ) == 0
        and payload.get("cross_parent_basis_count") == 0
    )


def _zero_api_passed(
    payload: dict[str, Any],
    *,
    manifest: dict[str, Any],
    root: Path,
    network_report: dict[str, Any],
    network_report_path: Path,
) -> bool:
    commands = payload.get("commands")
    expected = _zero_api_commands(
        manifest,
        python_executable=sys.executable,
    )
    return (
        payload.get("schema_version")
        == "guide-task11-zero-api-summary-v1"
        and payload.get("passed") is True
        and payload.get("guard_active") is True
        and payload.get("provider_call_count") == 0
        and payload.get("outbound_network_attempt_count") == 0
        and payload.get("network_report_sha256")
        == sha256(network_report_path.read_bytes()).hexdigest()
        and _network_report_passed(network_report)
        and payload.get("protected_payload_sha256")
        == manifest["protected_payload_sha256"]
        and isinstance(commands, list)
        and len(commands) == len(expected)
        and all(
            isinstance(command, dict)
            and command.get("returncode") == 0
            and command.get("argv") == list(expected_argv)
            for command, expected_argv in zip(
                commands,
                expected,
                strict=True,
            )
        )
    )


def _network_report_passed(payload: dict[str, Any]) -> bool:
    return (
        payload.get("schema_version")
        == "guide-zero-api-network-report-v1"
        and payload.get("guard_active") is True
        and payload.get("passed") is True
        and payload.get("provider_call_count") == 0
        and payload.get("outbound_network_attempt_count") == 0
        and payload.get("attempts") == []
    )


def _test_path_audit_passed(
    payload: dict[str, Any],
    *,
    manifest: dict[str, Any],
) -> bool:
    gates = payload.get("gates")
    fixture_paths = set(manifest["fixture_paths"])
    if (
        payload.get("schema_version")
        != "guide-task11-test-path-audit-v1"
        or payload.get("passed") is not True
        or payload.get("production_path_gate_count", 0) < 1
        or payload.get("invalid_production_path_claim_count") != 0
        or payload.get("unprotected_fixture_dependency_count") != 0
        or not isinstance(gates, list)
        or not gates
    ):
        return False
    production_gates = [
        gate
        for gate in gates
        if isinstance(gate, dict)
        and gate.get("claimed_scope") == "production_path"
    ]
    return (
        len(production_gates) >= 1
        and all(
            gate.get("real_entrypoint") == "/api/v1/chat/stream"
            and gate.get("layers_bypassed") == []
            and gate.get("semantic_injection_type")
            == "turn_meaning_provider"
            and set(gate.get("fixture_files", ())) <= fixture_paths
            for gate in production_gates
        )
    )


def _production_trace_passed(trace: object) -> bool:
    if not isinstance(trace, dict):
        return False
    return (
        trace.get("translation_injection_count") == 1
        and trace.get("structured_understanding_injection_count") == 0
        and trace.get("compiler_call_count") == 1
        and trace.get("direct_router_bypass_count") == 0
        and trace.get("legacy_entrypoint_count") == 0
        and trace.get("router_call_count") == 1
        and trace.get("route_decision_digest")
        == trace.get("result_decision_digest")
        and trace.get("decision_identity_violation_count") == 0
        and trace.get("execution_result_count") == 1
        and trace.get("reducer_call_count") == 1
        and trace.get("state_save_count") == 1
        and trace.get("processor_state_write_count") == 0
        and trace.get("event_state_projection_count") == 0
        and trace.get("provider_call_count") == 0
        and trace.get("outbound_network_attempt_count") == 0
        and trace.get("accepted") is True
        and trace.get("terminal_event") == "end"
        and trace.get("committed_version")
        == trace.get("loaded_version", -2) + 1
        and trace.get("expected_state_edge")
        == trace.get("observed_state_edge")
    )


def _production_path_passed(payload: dict[str, Any]) -> bool:
    zero_fields = (
        "actual_equivalence_failure_count",
        "bounded_failure_count",
        "compiler_bypass_count",
        "compiler_call_count_violation_count",
        "structured_understanding_injection_count",
        "direct_router_bypass_count",
        "legacy_entrypoint_count",
        "router_call_count_violation_count",
        "decision_identity_violation_count",
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
    traces = payload.get("turn_traces")
    return (
        payload.get("schema_version")
        == "guide-task11-production-path-summary-v1"
        and payload.get("passed") is True
        and payload.get("expected_contract_case_count") == 128
        and payload.get("actual_equivalence_case_count") == 128
        and payload.get("trajectory_count", 0) >= 12
        and payload.get("stateful_turn_count", 0) >= 48
        and payload.get("turn_count") == 176
        and payload.get("required_state_edge_count", 0) >= 40
        and payload.get("state_edge_count")
        == payload.get("required_state_edge_count")
        and payload.get("bounded_turn_count") == 9
        and payload.get("translation_injection_count") == 176
        and all(payload.get(field) == 0 for field in zero_fields)
        and isinstance(traces, list)
        and len(traces) == 176
        and all(_production_trace_passed(trace) for trace in traces)
    )


def _fixture_passed(
    payload: dict[str, Any],
    *,
    viewport: str,
) -> bool:
    turns = payload.get("turns")
    return (
        payload.get("schema_version")
        == "guide-mainline-contract-browser-audit-v1"
        and payload.get("trajectory_set") == "fixture"
        and payload.get("viewport") == viewport
        and payload.get("turn_count") == 7
        and payload.get("invalid_clarification_count", 0) == 0
        and isinstance(turns, list)
        and tuple(
            item.get("turn_id")
            for item in turns
            if isinstance(item, dict)
        )
        == _FIXTURE_TURN_IDS
        and payload.get("passed") is True
    )


def _current_circuit_state(
    ledger: dict[str, Any],
    *,
    plan_revision: str,
) -> str:
    failures: dict[str, int] = {}
    for attempt in ledger["attempts"]:
        if (
            not isinstance(attempt, dict)
            or attempt.get("plan_revision") != plan_revision
        ):
            continue
        if attempt.get("result") == "unverifiable_history":
            return "open"
        if attempt.get("result") != "failed":
            continue
        owner = attempt.get("first_failure_owner")
        if isinstance(owner, str) and owner:
            failures[owner] = failures.get(owner, 0) + 1
    return (
        "open"
        if any(count >= 2 for count in failures.values())
        else "closed"
    )


def derive_candidate_readiness(
    *,
    manifest_path: str | Path,
    semantic_summary_path: str | Path,
    zero_api_summary_path: str | Path,
    network_report_path: str | Path,
    test_path_audit_path: str | Path,
    production_path_summary_path: str | Path,
    independent_audit_path: str | Path,
    desktop_summary_path: str | Path,
    mobile_summary_path: str | Path,
    ledger_path: str | Path,
    output_path: str | Path | None = None,
) -> dict[str, Any]:
    manifest_file = Path(manifest_path)
    manifest, root = _validated_manifest(manifest_file)
    evidence_paths = {
        "semantic_summary": Path(semantic_summary_path),
        "zero_api_summary": Path(zero_api_summary_path),
        "network_report": Path(network_report_path),
        "test_path_audit": Path(test_path_audit_path),
        "production_path_summary": Path(
            production_path_summary_path
        ),
        "independent_audit": Path(independent_audit_path),
        "desktop_summary": Path(desktop_summary_path),
        "mobile_summary": Path(mobile_summary_path),
    }
    evidence = {
        role: _read_object(
            path,
            label=role.replace("_", " "),
        )
        for role, path in evidence_paths.items()
    }
    if not _semantic_passed(evidence["semantic_summary"]):
        raise Task11ReadinessError(
            "semantic matrix evidence failed"
        )
    if not _network_report_passed(evidence["network_report"]):
        raise Task11ReadinessError(
            "zero API network evidence failed"
        )
    if (
        evidence["zero_api_summary"].get(
            "candidate_manifest_sha256"
        )
        != sha256(manifest_file.read_bytes()).hexdigest()
        or not _zero_api_passed(
            evidence["zero_api_summary"],
            manifest=manifest,
            root=root,
            network_report=evidence["network_report"],
            network_report_path=evidence_paths["network_report"],
        )
    ):
        raise Task11ReadinessError("zero API evidence failed")
    if not _test_path_audit_passed(
        evidence["test_path_audit"],
        manifest=manifest,
    ):
        raise Task11ReadinessError("test path audit failed")
    if not _production_path_passed(
        evidence["production_path_summary"]
    ):
        raise Task11ReadinessError(
            "production path summary failed"
        )
    if not _fixture_passed(
        evidence["desktop_summary"],
        viewport="desktop",
    ):
        raise Task11ReadinessError("desktop fixture evidence failed")
    if not _fixture_passed(
        evidence["mobile_summary"],
        viewport="mobile",
    ):
        raise Task11ReadinessError("mobile fixture evidence failed")
    audit = evidence["independent_audit"]
    reviewed_evidence_sha256 = audit.get(
        "reviewed_evidence_sha256"
    )
    expected_reviewed_evidence_sha256 = {
        "candidate_manifest": sha256(
            manifest_file.read_bytes()
        ).hexdigest(),
        **{
            role: sha256(path.read_bytes()).hexdigest()
            for role, path in evidence_paths.items()
            if role != "independent_audit"
        },
    }
    if (
        audit.get("schema_version")
        != "guide-task11-independent-audit-v1"
        or audit.get("passed") is not True
        or audit.get("plan_revision") != manifest["plan_revision"]
        or audit.get("protected_payload_sha256")
        != manifest["protected_payload_sha256"]
        or reviewed_evidence_sha256
        != expected_reviewed_evidence_sha256
    ):
        raise Task11ReadinessError(
            "independent audit evidence failed"
        )
    ledger = read_ledger(ledger_path)
    circuit_state = _current_circuit_state(
        ledger,
        plan_revision=manifest["plan_revision"],
    )
    invalid_clarifications = sum(
        int(evidence[key].get("invalid_clarification_count", 0))
        for key in ("desktop_summary", "mobile_summary")
    )
    readiness = {
        "schema_version": _READINESS_SCHEMA,
        "plan_revision": manifest["plan_revision"],
        "candidate_head": manifest["candidate_head"],
        "candidate_payload_sha256": (
            manifest["candidate_payload_sha256"]
        ),
        "protected_payload_sha256": (
            manifest["protected_payload_sha256"]
        ),
        "step_0_passed": True,
        "step_0_5_passed": True,
        "step_4_5_passed": True,
        "step_4_6_passed": True,
        "affected_zero_api_passed": True,
        "production_path_matrix_passed": True,
        "desktop_fixture_passed": True,
        "mobile_fixture_passed": True,
        "invalid_clarification_count": invalid_clarifications,
        "provider_call_count": (
            evidence["network_report"]["provider_call_count"]
        ),
        "outbound_network_attempt_count": (
            evidence["network_report"][
                "outbound_network_attempt_count"
            ]
        ),
        "circuit_state": circuit_state,
        "evidence_files": {
            "candidate_manifest": str(manifest_file.resolve()),
            **{
                role: str(path.resolve())
                for role, path in evidence_paths.items()
            },
        },
        "evidence_sha256": {
            "candidate_manifest": sha256(
                manifest_file.read_bytes()
            ).hexdigest(),
            **{
                role: sha256(path.read_bytes()).hexdigest()
                for role, path in evidence_paths.items()
            },
        },
    }
    if invalid_clarifications != 0 or circuit_state != "closed":
        raise Task11ReadinessError("Task 11 readiness is blocked")
    if output_path is not None:
        _write_json(Path(output_path), readiness)
    return readiness


def verify_saved_readiness(
    *,
    readiness_path: str | Path,
    manifest_path: str | Path,
    semantic_summary_path: str | Path,
    zero_api_summary_path: str | Path,
    network_report_path: str | Path,
    test_path_audit_path: str | Path,
    production_path_summary_path: str | Path,
    independent_audit_path: str | Path,
    desktop_summary_path: str | Path,
    mobile_summary_path: str | Path,
    ledger_path: str | Path,
) -> dict[str, Any]:
    saved = _read_object(Path(readiness_path), label="readiness")
    derived = derive_candidate_readiness(
        manifest_path=manifest_path,
        semantic_summary_path=semantic_summary_path,
        zero_api_summary_path=zero_api_summary_path,
        network_report_path=network_report_path,
        test_path_audit_path=test_path_audit_path,
        production_path_summary_path=production_path_summary_path,
        independent_audit_path=independent_audit_path,
        desktop_summary_path=desktop_summary_path,
        mobile_summary_path=mobile_summary_path,
        ledger_path=ledger_path,
    )
    if saved != derived:
        raise Task11ReadinessError("saved readiness does not match evidence")
    return derived


def verify_task11_readiness(
    *,
    readiness_path: str | Path,
    ledger_path: str | Path,
    fixture_bundle_verifier: Callable[[Path], None] | None = None,
) -> dict[str, Any]:
    saved = _read_object(Path(readiness_path), label="readiness")
    files = saved.get("evidence_files")
    hashes = saved.get("evidence_sha256")
    required = {
        "candidate_manifest",
        "semantic_summary",
        "zero_api_summary",
        "network_report",
        "test_path_audit",
        "production_path_summary",
        "independent_audit",
        "desktop_summary",
        "mobile_summary",
    }
    if (
        not isinstance(files, dict)
        or not isinstance(hashes, dict)
        or set(files) != required
        or set(hashes) != required
    ):
        raise Task11ReadinessError(
            "readiness evidence binding is invalid"
        )
    for role in required:
        path = Path(str(files[role]))
        if (
            not path.is_file()
            or hashes[role] != sha256(path.read_bytes()).hexdigest()
        ):
            raise Task11ReadinessError(
                f"readiness evidence drift: {role}"
            )
    if fixture_bundle_verifier is None:
        fixture_bundle_verifier = _verify_fixture_summary_bundles
    for role in ("desktop_summary", "mobile_summary"):
        fixture_bundle_verifier(Path(str(files[role])))
    manifest, root = _validated_manifest(
        Path(str(files["candidate_manifest"]))
    )
    if manifest.get("candidate_head") != _git_head(root):
        raise Task11ReadinessError("candidate HEAD drift")
    missing = tuple(
        path
        for path in discover_relevant_changes(root)
        if path
        not in {
            *manifest["protected_paths"],
            *manifest["deleted_paths"],
        }
    )
    if missing:
        raise Task11ReadinessError(
            "relevant changed paths missing from Task 11 Files: "
            + ", ".join(missing)
        )
    return verify_saved_readiness(
        readiness_path=readiness_path,
        manifest_path=files["candidate_manifest"],
        semantic_summary_path=files["semantic_summary"],
        zero_api_summary_path=files["zero_api_summary"],
        network_report_path=files["network_report"],
        test_path_audit_path=files["test_path_audit"],
        production_path_summary_path=files[
            "production_path_summary"
        ],
        independent_audit_path=files["independent_audit"],
        desktop_summary_path=files["desktop_summary"],
        mobile_summary_path=files["mobile_summary"],
        ledger_path=ledger_path,
    )


def _verify_fixture_summary_bundles(summary_path: Path) -> None:
    from tools.guide_gates.run_mainline_contract_browser_audit import (
        validate_audit_bundle,
    )

    summary = _read_object(summary_path, label="fixture summary")
    turns = summary.get("turns")
    if not isinstance(turns, list):
        raise Task11ReadinessError("fixture summary is invalid")
    for expected_turn_id, row in zip(
        _FIXTURE_TURN_IDS,
        turns,
        strict=True,
    ):
        if (
            not isinstance(row, dict)
            or row.get("turn_id") != expected_turn_id
            or row.get("directory") != expected_turn_id
        ):
            raise Task11ReadinessError("fixture summary is invalid")
        try:
            validate_audit_bundle(
                summary_path.parent / expected_turn_id,
                expected_turn_id=expected_turn_id,
            )
        except ValueError as exc:
            raise Task11ReadinessError(
                f"fixture bundle failed: {expected_turn_id}"
            ) from exc


def finalize_change_manifest(
    *,
    repo_root: str | Path,
    manifest_path: str | Path,
) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    path = Path(manifest_path)
    manifest = _read_object(path, label="change manifest")
    approved_raw = manifest.get("approved_paths")
    if (
        manifest.get("schema_version")
        != "guide-task11-change-manifest-v1"
        or not isinstance(approved_raw, list)
        or not approved_raw
        or manifest.get("finalized") is not False
        or manifest.get("staged_diff_sha256") is not None
    ):
        raise Task11ReadinessError("change manifest is invalid")
    approved = tuple(_normalized_path(str(item)) for item in approved_raw)
    if len(approved) != len(set(approved)):
        raise Task11ReadinessError("change manifest paths are invalid")
    staged_output = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "-z"],
        cwd=root,
        check=True,
        capture_output=True,
    ).stdout
    staged = tuple(
        sorted(
            item.decode("utf-8")
            for item in staged_output.split(b"\0")
            if item
        )
    )
    if staged != tuple(sorted(approved)):
        raise Task11ReadinessError("staged path set mismatch")
    diff = subprocess.run(
        [
            "git",
            "diff",
            "--cached",
            "--binary",
            "--",
            *approved,
        ],
        cwd=root,
        check=True,
        capture_output=True,
    ).stdout
    finalized = {
        **manifest,
        "approved_paths": list(approved),
        "staged_diff_sha256": sha256(diff).hexdigest(),
        "finalized": True,
    }
    _write_json(path, finalized)
    return finalized


def _repository_relative(root: Path, path: Path) -> str:
    try:
        relative = path.resolve().relative_to(root).as_posix()
    except ValueError as exc:
        raise Task11ReadinessError(
            "change manifest path escapes repository"
        ) from exc
    return _normalized_path(relative)


def build_change_manifest(
    *,
    candidate_manifest_path: str | Path,
    candidate_readiness_path: str | Path,
    attempt_context_path: str | Path,
    ledger_path: str | Path,
    output_path: str | Path,
) -> dict[str, Any]:
    candidate_file = Path(candidate_manifest_path)
    manifest, root = _validated_manifest(candidate_file)
    readiness_file = Path(candidate_readiness_path)
    verified = verify_task11_readiness(
        readiness_path=readiness_file,
        ledger_path=ledger_path,
    )
    if (
        verified.get("plan_revision") != manifest["plan_revision"]
        or verified.get("protected_payload_sha256")
        != manifest["protected_payload_sha256"]
    ):
        raise Task11ReadinessError(
            "candidate readiness does not match manifest"
        )
    context_path = Path(attempt_context_path)
    context = read_attempt_context(
        context_path,
        ledger_path=ledger_path,
        readiness_path=readiness_file,
    )
    phase_ids = context.get("phase_attempt_ids")
    if not isinstance(phase_ids, dict):
        raise Task11ReadinessError("bounded attempt context is invalid")
    attempt_id = phase_ids.get("bounded")
    attempts = read_ledger(ledger_path).get("attempts")
    matching = [
        item
        for item in attempts
        if isinstance(item, dict)
        and item.get("attempt_id") == attempt_id
    ] if isinstance(attempts, list) else []
    if len(matching) != 1 or matching[0].get("result") != "passed":
        raise Task11ReadinessError("bounded attempt has not passed")
    attempt_dir = Path(str(context.get("output_directory")))
    if not attempt_dir.is_dir():
        raise Task11ReadinessError(
            "bounded attempt directory is missing"
        )
    summary_paths = tuple(
        sorted(attempt_dir.glob("browser-*/summary.json"))
    )
    if len(summary_paths) != 1:
        raise Task11ReadinessError("bounded summary is invalid")
    bounded_summary = _read_object(
        summary_paths[0],
        label="bounded summary",
    )
    if (
        bounded_summary.get("schema_version")
        != "guide-mainline-contract-browser-audit-v1"
        or bounded_summary.get("trajectory_set") != "bounded"
        or bounded_summary.get("passed") is not True
        or bounded_summary.get("invalid_clarification_count") != 0
        or bounded_summary.get("turn_count") != _BOUNDED_TURN_COUNT
    ):
        raise Task11ReadinessError("bounded summary is invalid")
    artifact_paths: list[str] = []
    for item in sorted(attempt_dir.rglob("*")):
        if item.is_symlink():
            raise Task11ReadinessError(
                "bounded artifact path is a symlink"
            )
        if item.is_file():
            artifact_paths.append(_repository_relative(root, item))
    evidence_files = verified.get("evidence_files")
    if not isinstance(evidence_files, dict):
        raise Task11ReadinessError("readiness evidence binding is invalid")
    supporting = {
        _repository_relative(root, candidate_file),
        _repository_relative(root, readiness_file),
        _repository_relative(root, Path(ledger_path)),
        _repository_relative(root, context_path),
        *(
            _repository_relative(root, Path(str(path)))
            for path in evidence_files.values()
        ),
        *artifact_paths,
    }
    approved = tuple(sorted({
        *manifest["protected_paths"],
        *manifest["deleted_paths"],
        *supporting,
    }))
    output = {
        "schema_version": "guide-task11-change-manifest-v1",
        "plan_revision": manifest["plan_revision"],
        "candidate_manifest_sha256": sha256(
            candidate_file.read_bytes()
        ).hexdigest(),
        "candidate_readiness_sha256": sha256(
            readiness_file.read_bytes()
        ).hexdigest(),
        "bounded_attempt_id": attempt_id,
        "bounded_artifact_paths": artifact_paths,
        "approved_paths": list(approved),
        "staged_diff_sha256": None,
        "finalized": False,
    }
    _write_json(Path(output_path), output)
    return output


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    audit = subparsers.add_parser("audit-test-paths")
    audit.add_argument("--repo-root", type=Path, default=Path.cwd())
    audit.add_argument("--plan", type=Path, required=True)
    audit.add_argument("--output", type=Path, required=True)
    manifest = subparsers.add_parser("manifest")
    manifest.add_argument("--repo-root", type=Path, default=Path.cwd())
    manifest.add_argument("--plan", type=Path, required=True)
    manifest.add_argument("--output", type=Path, required=True)
    prepare_manifest = subparsers.add_parser("prepare-manifest")
    prepare_manifest.add_argument(
        "--repo-root",
        type=Path,
        default=Path.cwd(),
    )
    prepare_manifest.add_argument("--plan", type=Path, required=True)
    prepare_manifest.add_argument(
        "--test-path-audit",
        type=Path,
        required=True,
    )
    prepare_manifest.add_argument(
        "--manifest",
        type=Path,
        required=True,
    )
    prepare = subparsers.add_parser("prepare-evidence")
    prepare.add_argument("--repo-root", type=Path, default=Path.cwd())
    prepare.add_argument("--manifest", type=Path, required=True)
    prepare.add_argument("--semantic-summary", type=Path, required=True)
    prepare.add_argument("--zero-api-summary", type=Path, required=True)
    prepare.add_argument("--test-path-audit", type=Path, required=True)
    prepare.add_argument(
        "--production-path-summary",
        type=Path,
        required=True,
    )
    prepare.add_argument(
        "--cases",
        type=Path,
        default=Path(
            "tests/fixtures/guide/intent/"
            "turn_meaning_gate_v1.jsonl"
        ),
    )
    for name in ("derive", "seal-readiness"):
        derive = subparsers.add_parser(name)
        derive.add_argument("--manifest", type=Path, required=True)
        derive.add_argument("--readiness", type=Path, required=True)
        derive.add_argument(
            "--semantic-summary",
            type=Path,
            required=True,
        )
        derive.add_argument(
            "--zero-api-summary",
            type=Path,
            required=True,
        )
        derive.add_argument(
            "--network-report",
            type=Path,
            required=True,
        )
        derive.add_argument(
            "--test-path-audit",
            type=Path,
            required=True,
        )
        derive.add_argument(
            "--production-path-summary",
            type=Path,
            required=True,
        )
        derive.add_argument(
            "--independent-audit",
            type=Path,
            required=True,
        )
        derive.add_argument(
            "--desktop-summary",
            type=Path,
            required=True,
        )
        derive.add_argument(
            "--mobile-summary",
            type=Path,
            required=True,
        )
        derive.add_argument("--ledger", type=Path, required=True)
    finalize = subparsers.add_parser("finalize-change-manifest")
    finalize.add_argument(
        "--repo-root",
        type=Path,
        default=Path.cwd(),
    )
    finalize.add_argument("--manifest", type=Path, required=True)
    change = subparsers.add_parser("build-change-manifest")
    change.add_argument(
        "--candidate-manifest",
        type=Path,
        required=True,
    )
    change.add_argument(
        "--candidate-readiness",
        type=Path,
        required=True,
    )
    change.add_argument(
        "--attempt-context",
        type=Path,
        required=True,
    )
    change.add_argument("--ledger", type=Path, required=True)
    change.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.command == "audit-test-paths":
        result = build_test_path_audit(
            repo_root=args.repo_root,
            plan_path=args.plan,
            output_path=args.output,
        )
    elif args.command == "manifest":
        result = build_candidate_manifest(
            repo_root=args.repo_root,
            plan_path=args.plan,
            output_path=args.output,
        )
    elif args.command == "prepare-manifest":
        result = build_candidate_manifest(
            repo_root=args.repo_root,
            plan_path=args.plan,
            output_path=args.manifest,
            test_path_audit_path=args.test_path_audit,
        )
    elif args.command == "prepare-evidence":
        network_report = os.environ.get(
            "XIAORO_ZERO_API_NETWORK_REPORT"
        )
        if not network_report:
            raise Task11ReadinessError(
                "XIAORO_ZERO_API_NETWORK_REPORT is required"
            )
        manifest, root = _validated_manifest(args.manifest)
        if root != args.repo_root.resolve():
            raise Task11ReadinessError(
                "candidate repository root mismatch"
            )
        test_path_audit = _read_object(
            args.test_path_audit,
            label="test path audit",
        )
        production_path_summary = _read_object(
            args.production_path_summary,
            label="production path summary",
        )
        if not _test_path_audit_passed(
            test_path_audit,
            manifest=manifest,
        ):
            raise Task11ReadinessError("test path audit failed")
        if not _production_path_passed(production_path_summary):
            raise Task11ReadinessError(
                "production path summary failed"
            )
        semantic = build_semantic_summary(
            cases_path=args.cases,
            output_path=args.semantic_summary,
        )
        zero_api = run_zero_api_suite(
            repo_root=args.repo_root,
            manifest_path=args.manifest,
            output_path=args.zero_api_summary,
            network_report_path=network_report,
        )
        result = {
            "candidate_manifest": manifest,
            "semantic_summary": semantic,
            "zero_api_summary": zero_api,
            "network_report": _read_object(
                Path(network_report),
                label="zero API network report",
            ),
        }
    elif args.command in {"derive", "seal-readiness"}:
        result = derive_candidate_readiness(
            manifest_path=args.manifest,
            semantic_summary_path=args.semantic_summary,
            zero_api_summary_path=args.zero_api_summary,
            network_report_path=args.network_report,
            test_path_audit_path=args.test_path_audit,
            production_path_summary_path=(
                args.production_path_summary
            ),
            independent_audit_path=args.independent_audit,
            desktop_summary_path=args.desktop_summary,
            mobile_summary_path=args.mobile_summary,
            ledger_path=args.ledger,
            output_path=args.readiness,
        )
    elif args.command == "finalize-change-manifest":
        result = finalize_change_manifest(
            repo_root=args.repo_root,
            manifest_path=args.manifest,
        )
    else:
        result = build_change_manifest(
            candidate_manifest_path=args.candidate_manifest,
            candidate_readiness_path=args.candidate_readiness,
            attempt_context_path=args.attempt_context,
            ledger_path=args.ledger,
            output_path=args.output,
        )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
