"""Aggregate the focused and production-equivalent release gates."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Mapping, Sequence

from tools.guide_gates.attempt_ledger import (
    attempt_context_phase,
    ledger_anchor,
    read_attempt_context,
    read_ledger,
    verify_ledger_extension,
)
from tools.guide_gates.build_task11_readiness import (
    verify_task11_readiness,
)
from tools.guide_gates.build_responsibility_matrix import (
    build_responsibility_matrix_rows,
)
from tools.guide_gates.run_final_real_translation import (
    FINAL_TRANSLATION_FIXTURE_PATH,
)
from tools.guide_gates.run_mainline_contract_browser_audit import (
    AuditBundleError,
    derive_release_turn_counters,
    validate_audit_bundle,
)


_REPO_ROOT = Path(__file__).resolve().parents[2]
_GUIDE_RENDERER = _REPO_ROOT / "app/static/guide-presentation.js"
_CHAT_PAGE = _REPO_ROOT / "app/static/chat.html"
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")
_RELEASE_PLAN_PATHS = (
    "docs/superpowers/plans/2026-08-20-final-guide-release-closure.md",
    "docs/superpowers/plans/2026-08-21-guide-mainline-contract-closure.md",
)
_RELEASE_ROOT_FILES = (
    ".env.example",
    "Dockerfile",
    "docker-compose.prod.yml",
    "docker-compose.yml",
    "docker-compose.yaml",
    "init.sql",
    "nginx.conf",
    "pytest-guide.ini",
    "requirements-guide-browser-matrix.txt",
    "requirements-guide-image.txt",
    "requirements-guide-runtime-test.txt",
    "requirements-guide-runtime.txt",
    "requirements.txt",
    "start.sh",
)
_MANUAL_REVIEW_MODES = (
    "explore_recommendation",
    "fit_recommendation",
    "product_knowledge",
    "comparison",
    "image_identity",
    "image_fit_recommendation",
    "image_comparison",
)


class FinalReleaseGateError(ValueError):
    pass


def _write_json_exclusive(
    path: Path,
    payload: Mapping[str, object],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (
        json.dumps(
            dict(payload),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")
    try:
        with path.open("xb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as exc:
        raise FinalReleaseGateError(
            f"release artifact already exists: {path}"
        ) from exc
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def _verified_context(
    *,
    attempt_context_path: str | Path,
    expected_tail_phase: str,
    repo_root: str | Path,
) -> tuple[dict[str, object], Path, Path, dict[str, object]]:
    root = Path(repo_root).resolve()
    context_path = Path(attempt_context_path).resolve()
    raw = _read_json(context_path)
    ledger_path = Path(str(raw.get("ledger_path"))).resolve()
    readiness_path = Path(str(raw.get("readiness_path"))).resolve()
    context = read_attempt_context(
        context_path,
        ledger_path=ledger_path,
        readiness_path=readiness_path,
    )
    verify_task11_readiness(
        readiness_path=readiness_path,
        ledger_path=ledger_path,
        expected_manifest_sha256=str(
            context.get("expected_manifest_sha256")
        ),
    )
    output = Path(str(context.get("output_directory"))).resolve()
    phase_ids = context.get("phase_attempt_ids")
    if (
        output != context_path.parent
        or not output.is_dir()
        or root not in output.parents
        or not isinstance(phase_ids, dict)
        or not phase_ids
        or attempt_context_phase(context) != expected_tail_phase
    ):
        raise FinalReleaseGateError(
            "attempt context output or phase binding is invalid"
        )
    ledger = read_ledger(ledger_path)
    return context, output, ledger_path, ledger


def _verified_post_real_context(
    *,
    attempt_context_path: str | Path,
    expected_tail_phase: str,
    require_head: str,
    require_task11_head: bool,
    repo_root: str | Path,
) -> tuple[
    dict[str, object],
    Path,
    Path,
    dict[str, object],
    dict[str, object],
]:
    root = Path(repo_root).resolve()
    context_path = Path(attempt_context_path).resolve()
    raw = _read_json(context_path)
    ledger_path = Path(str(raw.get("ledger_path"))).resolve()
    readiness_path = Path(str(raw.get("readiness_path"))).resolve()
    context = read_attempt_context(
        context_path,
        ledger_path=ledger_path,
        readiness_path=readiness_path,
    )
    if context.get("readiness_sha256") != _file_sha256(readiness_path):
        raise FinalReleaseGateError(
            "post-real attempt readiness hash mismatch"
        )
    readiness = _verify_post_real_readiness(
        readiness_path=readiness_path,
        ledger_path=ledger_path,
        require_head=require_head,
        repo_root=root,
    )
    if (
        require_task11_head
        and readiness.get("task11_commit") != require_head
    ):
        raise FinalReleaseGateError(
            "post-real manifest requires Task 11 HEAD"
        )
    output = Path(str(context.get("output_directory"))).resolve()
    phase_ids = context.get("phase_attempt_ids")
    if (
        output != context_path.parent
        or not output.is_dir()
        or root not in output.parents
        or not isinstance(phase_ids, dict)
        or not phase_ids
        or attempt_context_phase(context) != expected_tail_phase
    ):
        raise FinalReleaseGateError(
            "post-real attempt context binding is invalid"
        )
    ledger = read_ledger(ledger_path)
    return context, output, ledger_path, ledger, readiness


def _attempt(
    ledger: Mapping[str, object],
    *,
    attempt_id: object,
) -> dict[str, object]:
    attempts = ledger.get("attempts")
    matches = [
        item
        for item in attempts
        if isinstance(item, dict)
        and item.get("attempt_id") == attempt_id
    ] if isinstance(attempts, list) else []
    if len(matches) != 1:
        raise FinalReleaseGateError("attempt context is invalid")
    return matches[0]


def run_focused_phase(
    *,
    responsibility_matrix: str | Path,
    attempt_context_path: str | Path,
    repo_root: str | Path = _REPO_ROOT,
) -> dict[str, object]:
    context, output, _, ledger = _verified_context(
        attempt_context_path=attempt_context_path,
        expected_tail_phase="translation",
        repo_root=repo_root,
    )
    phase_ids = context["phase_attempt_ids"]
    attempt = _attempt(
        ledger,
        attempt_id=phase_ids["translation"],
    )
    if (
        attempt.get("trajectory_set") != "translation"
        or attempt.get("result") != "allocated"
        or attempt.get("context_path")
        != str(Path(attempt_context_path).resolve())
    ):
        raise FinalReleaseGateError(
            "focused phase requires allocated translation attempt"
        )
    result = run_focused_gate(Path(responsibility_matrix))
    _write_json_exclusive(output / "focused.json", result)
    if result.get("passed") is not True:
        raise FinalReleaseGateError("focused release gate failed")
    return result


def run_aggregate_phase(
    *,
    attempt_context_path: str | Path,
    repo_root: str | Path = _REPO_ROOT,
) -> dict[str, object]:
    context, output, _, ledger = _verified_context(
        attempt_context_path=attempt_context_path,
        expected_tail_phase="browser",
        repo_root=repo_root,
    )
    phase_ids = context["phase_attempt_ids"]
    translation_attempt = _attempt(
        ledger,
        attempt_id=phase_ids.get("translation"),
    )
    browser_attempt = _attempt(
        ledger,
        attempt_id=phase_ids.get("browser"),
    )
    if (
        translation_attempt.get("trajectory_set") != "translation"
        or translation_attempt.get("result") != "passed"
        or browser_attempt.get("trajectory_set") != "browser"
        or browser_attempt.get("result") != "passed"
        or browser_attempt.get("context_path")
        != str(Path(attempt_context_path).resolve())
    ):
        raise FinalReleaseGateError(
            "aggregate phase attempt chain is invalid"
        )
    translation_context = Path(
        str(translation_attempt.get("context_path"))
    ).resolve()
    translation_output = translation_context.parent
    inputs = {
        "focused": translation_output / "focused.json",
        "translation": (
            translation_output / "real-translation/summary.json"
        ),
        "backend": translation_output / "real-backend/summary.json",
        "browser": output / "mainline-browser/summary.json",
        "manual_review": output / "manual-screenshot-review.json",
    }
    payloads = {
        role: _read_json(path)
        for role, path in inputs.items()
    }
    _validate_aggregate_bindings(
        repo_root=Path(repo_root).resolve(),
        context_path=Path(attempt_context_path).resolve(),
        context=context,
        readiness_path=Path(str(context.get("readiness_path"))).resolve(),
        focused_path=inputs["focused"],
        translation_directory=(
            translation_output / "real-translation"
        ),
        translation_summary=payloads["translation"],
        backend_directory=translation_output / "real-backend",
        backend_summary=payloads["backend"],
        browser_summary_path=inputs["browser"],
        browser_summary=payloads["browser"],
        manual_review=payloads["manual_review"],
        browser_attempt=browser_attempt,
    )
    result = aggregate_release_gate(**payloads)
    _write_json_exclusive(output / "release-summary.json", result)
    if result.get("passed") is not True:
        raise FinalReleaseGateError("aggregate release gate failed")
    return result


def _validate_aggregate_bindings(
    *,
    repo_root: Path,
    context_path: Path,
    context: Mapping[str, object],
    readiness_path: Path,
    focused_path: Path,
    translation_directory: Path,
    translation_summary: Mapping[str, object],
    backend_directory: Path,
    backend_summary: Mapping[str, object],
    browser_summary_path: Path,
    browser_summary: Mapping[str, object],
    manual_review: Mapping[str, object],
    browser_attempt: Mapping[str, object],
) -> None:
    if (
        manual_review.get("attempt_id")
        != browser_attempt.get("attempt_id")
        or manual_review.get("code_revision")
        != browser_attempt.get("code_revision")
        or manual_review.get("attempt_context_path")
        != _repository_relative(repo_root, context_path)
        or manual_review.get("attempt_context_sha256")
        != _file_sha256(context_path)
        or manual_review.get("readiness_path")
        != _repository_relative(repo_root, readiness_path)
        or manual_review.get("readiness_sha256")
        != _file_sha256(readiness_path)
        or manual_review.get("readiness_sha256")
        != context.get("readiness_sha256")
        or manual_review.get("browser_summary_path")
        != _repository_relative(repo_root, browser_summary_path)
    ):
        raise FinalReleaseGateError(
            "manual review release context binding is invalid"
        )
    if manual_review.get("browser_summary_sha256") != _file_sha256(
        browser_summary_path
    ):
        raise FinalReleaseGateError(
            "manual review browser summary hash mismatch"
        )
    if (
        browser_summary.get("schema_version")
        != "guide-mainline-contract-browser-audit-v1"
        or browser_summary.get("trajectory_set") != "release"
        or browser_summary.get("viewport") != "all"
    ):
        raise FinalReleaseGateError(
            "release browser summary binding is invalid"
        )
    _validate_browser_release_evidence(
        repo_root=repo_root,
        output=browser_summary_path.parent.parent,
        browser_summary=browser_summary,
    )
    fixture_path = repo_root / FINAL_TRANSLATION_FIXTURE_PATH
    if (
        not fixture_path.is_file()
        or fixture_path.is_symlink()
        or translation_summary.get("fixture_path")
        != FINAL_TRANSLATION_FIXTURE_PATH
        or backend_summary.get("fixture_path")
        != FINAL_TRANSLATION_FIXTURE_PATH
        or translation_summary.get("fixture_sha256")
        != _file_sha256(fixture_path)
        or backend_summary.get("fixture_sha256")
        != _file_sha256(fixture_path)
    ):
        raise FinalReleaseGateError(
            "release translation fixture binding is invalid"
        )
    translation_index = _indexed_checksum_directory(
        repo_root,
        translation_directory,
    )
    backend_index = _indexed_checksum_directory(
        repo_root,
        backend_directory,
    )
    if (
        translation_summary.get("results_sha256")
        != translation_index[
            _repository_relative(
                repo_root,
                translation_directory / "results.jsonl",
            )
        ]
        or backend_summary.get("results_sha256")
        != backend_index[
            _repository_relative(
                repo_root,
                backend_directory / "results.jsonl",
            )
        ]
    ):
        raise FinalReleaseGateError(
            "release result checksum binding is invalid"
        )
    if translation_summary.get(
        "focused_summary_sha256"
    ) != _file_sha256(focused_path):
        raise FinalReleaseGateError(
            "translation focused summary hash mismatch"
        )
    expected_translation_hashes = {
        "translation_results_sha256": translation_index[
            _repository_relative(
                repo_root,
                translation_directory / "results.jsonl",
            )
        ],
        "translation_summary_sha256": translation_index[
            _repository_relative(
                repo_root,
                translation_directory / "summary.json",
            )
        ],
        "translation_checksums_sha256": translation_index[
            _repository_relative(
                repo_root,
                translation_directory / "SHA256SUMS",
            )
        ],
    }
    if any(
        backend_summary.get(key) != expected
        for key, expected in expected_translation_hashes.items()
    ):
        raise FinalReleaseGateError(
            "translation capture hash mismatch"
        )


def run_focused_gate(
    responsibility_matrix: Path,
) -> dict[str, object]:
    matrix_dir = Path(responsibility_matrix)
    summary_path = matrix_dir / "summary.json"
    truth_path = matrix_dir / "truth.jsonl"
    summary = _read_json(summary_path)
    actual_rows = tuple(
        json.loads(line)
        for line in truth_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    )
    expected_rows = build_responsibility_matrix_rows()
    row_count = len(actual_rows)
    legal_row_failures = 0
    wrong_processor_count = 0
    wrong_presentation_count = 0
    for index, expected in enumerate(expected_rows):
        actual = actual_rows[index] if index < row_count else None
        if actual != expected:
            legal_row_failures += 1
        if (
            actual is not None
            and actual.get("expected_processor")
            != expected["expected_processor"]
        ):
            wrong_processor_count += 1
        if (
            actual is not None
            and actual.get("expected_presentation_mode")
            != expected["expected_presentation_mode"]
        ):
            wrong_presentation_count += 1
    legal_row_failures += abs(row_count - len(expected_rows))
    expected_hash = sha256(
        truth_path.read_bytes()
    ).hexdigest()
    matrix_hash_mismatch = int(
        summary.get("truth_sha256") != expected_hash
    )
    forbidden_public_text_count = _forbidden_public_text_count()
    passed = (
        row_count == len(expected_rows)
        and legal_row_failures == 0
        and wrong_processor_count == 0
        and wrong_presentation_count == 0
        and matrix_hash_mismatch == 0
        and forbidden_public_text_count == 0
    )
    return {
        "schema_version": "guide-final-focused-gate-v1",
        "passed": passed,
        "row_count": row_count,
        "legal_row_failures": legal_row_failures,
        "wrong_binding_count": 0,
        "wrong_processor_count": wrong_processor_count,
        "wrong_presentation_count": wrong_presentation_count,
        "forbidden_public_text_count": forbidden_public_text_count,
        "matrix_hash_mismatch": matrix_hash_mismatch,
        "matrix_summary": summary,
    }


def aggregate_release_gate(
    *,
    focused: Mapping[str, object],
    translation: Mapping[str, object],
    backend: Mapping[str, object],
    browser: Mapping[str, object],
    manual_review: Mapping[str, object],
) -> dict[str, object]:
    if focused.get("schema_version") not in {
        None,
        "guide-final-focused-gate-v1",
    }:
        raise ValueError("focused summary schema is invalid")
    summaries = (translation, backend, browser)
    wrong_binding_count = _sum(
        focused,
        *summaries,
        key="wrong_binding_count",
    )
    wrong_processor_count = _int(focused, "wrong_processor_count")
    wrong_presentation_count = _sum(
        focused,
        backend,
        key="wrong_presentation_count",
    )
    unsafe_downgrade_count = _sum(
        translation,
        backend,
        key="unsafe_downgrade_count",
    )
    raw_ad_leak_count = _int(backend, "raw_ad_leak_count")
    internal_language_count = sum(
        max(
            _int(summary, "internal_language_count"),
            _int(summary, "internal_public_language_count"),
        )
        for summary in (translation, backend)
    )
    frontend_contract_violation_count = _sum(
        backend,
        browser,
        key="frontend_contract_violation_count",
    )
    unaligned_price_specification_count = _int(
        browser,
        "unaligned_price_specification_count",
    )
    copywriter_fallback_count = _int(
        browser,
        "copywriter_fallback_count",
    )
    invalid_clarification_count = _int(
        browser,
        "invalid_clarification_count",
    )
    context_mismatch_count = _int(
        backend,
        "context_mismatch_count",
    )
    manual_screenshot_review_count = _int(
        manual_review,
        "manual_screenshot_review_count",
    )
    manual_screenshot_failure_count = _int(
        manual_review,
        "manual_screenshot_failure_count",
    )
    declared_serious_failures = _sum(
        *summaries,
        key="serious_failure_count",
    )
    thresholds_passed = (
        bool(focused.get("passed"))
        and _translation_threshold(translation)
        and _backend_threshold(backend)
        and _browser_threshold(browser)
        and manual_review.get("schema_version")
        == "guide-manual-screenshot-review-v1"
        and manual_review.get("passed") is True
        and manual_screenshot_review_count == 14
        and manual_screenshot_failure_count == 0
    )
    any_release_counter = any(
        value > 0
        for value in (
            wrong_binding_count,
            wrong_processor_count,
            wrong_presentation_count,
            unsafe_downgrade_count,
            raw_ad_leak_count,
            internal_language_count,
            frontend_contract_violation_count,
            unaligned_price_specification_count,
            copywriter_fallback_count,
            invalid_clarification_count,
            context_mismatch_count,
            manual_screenshot_failure_count,
        )
    )
    serious_failure_count = declared_serious_failures + int(
        not thresholds_passed or any_release_counter
    )
    return {
        "schema_version": "guide-final-release-summary-v1",
        "passed": serious_failure_count == 0,
        "serious_failure_count": serious_failure_count,
        "wrong_binding_count": wrong_binding_count,
        "wrong_processor_count": wrong_processor_count,
        "wrong_presentation_count": wrong_presentation_count,
        "unsafe_downgrade_count": unsafe_downgrade_count,
        "raw_ad_leak_count": raw_ad_leak_count,
        "internal_language_count": internal_language_count,
        "frontend_contract_violation_count": (
            frontend_contract_violation_count
        ),
        "unaligned_price_specification_count": (
            unaligned_price_specification_count
        ),
        "copywriter_fallback_count": copywriter_fallback_count,
        "invalid_clarification_count": invalid_clarification_count,
        "context_mismatch_count": context_mismatch_count,
        "manual_screenshot_review_count": (
            manual_screenshot_review_count
        ),
        "manual_screenshot_failure_count": (
            manual_screenshot_failure_count
        ),
        "focused": dict(focused),
        "translation": dict(translation),
        "backend": dict(backend),
        "browser": dict(browser),
        "manual_review": dict(manual_review),
    }


def _translation_threshold(summary: Mapping[str, object]) -> bool:
    return (
        summary.get("schema_version")
        in {None, "guide-final-real-translation-summary-v1"}
        and
        bool(summary.get("passed"))
        and _complete_critical_trajectories(summary)
        and _int(summary, "turn_count") >= 48
        and _int(summary, "passed_turn_count") >= 46
    )


def _backend_threshold(summary: Mapping[str, object]) -> bool:
    return (
        summary.get("schema_version")
        in {None, "guide-final-real-backend-summary-v1"}
        and
        bool(summary.get("passed"))
        and _complete_critical_trajectories(summary)
        and _int(summary, "turn_count") >= 48
        and _int(summary, "completed_turn_count") >= 48
        and _int(summary, "context_mismatch_count") == 0
    )


def _browser_threshold(summary: Mapping[str, object]) -> bool:
    return (
        summary.get("schema_version")
        in {None, "guide-mainline-contract-browser-audit-v1"}
        and bool(summary.get("passed"))
        and _int(summary, "turn_count") >= 14
        and _int(summary, "serious_failure_count") == 0
        and _int(summary, "frontend_contract_violation_count") == 0
        and _int(summary, "wrong_binding_count") == 0
        and _int(summary, "unaligned_price_specification_count") == 0
        and _int(summary, "copywriter_fallback_count") == 0
        and _int(summary, "invalid_clarification_count") == 0
    )


def _complete_critical_trajectories(
    summary: Mapping[str, object],
) -> bool:
    return (
        _int(summary, "critical_trajectory_count") == 12
        and _int(summary, "critical_trajectory_passed") == 12
    )


def _forbidden_public_text_count() -> int:
    renderer = _GUIDE_RENDERER.read_text(encoding="utf-8")
    renderer_view = _between(
        renderer,
        "function buildPresentationView",
        "function renderRecommendationPresentation",
    )
    shelf = _between(
        _CHAT_PAGE.read_text(encoding="utf-8"),
        "function displayProducts(",
        "// 显示来源引用",
    )
    forbidden = (
        "directAnswer",
        "state.message",
        "p.rerank_reason",
        "p.description",
        "p.category_facts",
        "p.matched_efficacies",
        "buildDetailedProductReason(",
        "getSkinEvidenceLabel(",
        "适配待确认",
        "recommendation-reason",
    )
    return sum(
        renderer_view.count(term) + shelf.count(term)
        for term in forbidden
    )


def _between(text: str, start: str, end: str) -> str:
    start_index = text.index(start)
    end_index = text.index(end, start_index)
    return text[start_index:end_index]


def _read_json(path: Path) -> dict[str, object]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _int(summary: Mapping[str, object], key: str) -> int:
    if key not in summary:
        raise ValueError(f"{key} must be present")
    value = summary[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{key} must be an integer")
    return value


def _sum(
    *summaries: Mapping[str, object],
    key: str,
) -> int:
    return sum(_int(summary, key) for summary in summaries)


def _repository_relative(root: Path, path: Path) -> str:
    try:
        relative = path.resolve().relative_to(root).as_posix()
    except ValueError as exc:
        raise FinalReleaseGateError(
            "release artifact escapes repository"
        ) from exc
    if (
        not relative
        or relative.startswith("../")
        or path.is_symlink()
    ):
        raise FinalReleaseGateError("release artifact path is invalid")
    return relative


def _repository_regular_file(
    root: Path,
    value: str | Path,
    *,
    label: str,
) -> Path:
    candidate = Path(value)
    lexical = Path(
        os.path.abspath(
            candidate if candidate.is_absolute() else root / candidate
        )
    )
    try:
        relative = lexical.relative_to(root)
    except ValueError as exc:
        raise FinalReleaseGateError(
            f"{label} path escapes repository"
        ) from exc
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise FinalReleaseGateError(
                f"{label} path uses a symlink"
            )
    if not lexical.is_file():
        raise FinalReleaseGateError(f"{label} path is missing")
    return lexical


def _file_sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _canonical_payload_sha256(
    root: Path,
    paths: Sequence[str],
) -> str:
    digest = sha256()
    for relative in sorted(paths):
        path = root / relative
        if not path.is_file() or path.is_symlink():
            raise FinalReleaseGateError(
                f"release artifact is invalid: {relative}"
            )
        name = relative.encode("utf-8")
        content = path.read_bytes()
        digest.update(str(len(name)).encode("ascii"))
        digest.update(b":")
        digest.update(name)
        digest.update(str(len(content)).encode("ascii"))
        digest.update(b":")
        digest.update(content)
    return digest.hexdigest()


def _canonical_committed_payload_sha256(
    root: Path,
    *,
    revision: str,
    paths: Sequence[str],
) -> str:
    digest = sha256()
    for relative in sorted(paths):
        normalized = _normalized_release_path(relative)
        name = normalized.encode("utf-8")
        content = _committed_bytes(
            root,
            revision=revision,
            relative=normalized,
        )
        digest.update(str(len(name)).encode("ascii"))
        digest.update(b":")
        digest.update(name)
        digest.update(str(len(content)).encode("ascii"))
        digest.update(b":")
        digest.update(content)
    return digest.hexdigest()


def _current_execution_paths(root: Path) -> tuple[str, ...]:
    tracked = subprocess.run(
        [
            "git",
            "ls-files",
            "-z",
            "--",
            "app",
            "tools",
            "tests",
            *_RELEASE_ROOT_FILES,
        ],
        cwd=root,
        check=True,
        capture_output=True,
    ).stdout
    untracked = subprocess.run(
        [
            "git",
            "ls-files",
            "--others",
            "--exclude-standard",
            "-z",
            "--",
            "app",
            "tools",
            "tests",
            *_RELEASE_ROOT_FILES,
        ],
        cwd=root,
        check=True,
        capture_output=True,
    ).stdout
    paths: set[str] = set()
    for raw in (tracked + untracked).split(b"\0"):
        if not raw:
            continue
        try:
            relative = _normalized_release_path(raw.decode("utf-8"))
        except UnicodeDecodeError as exc:
            raise FinalReleaseGateError(
                "release execution path is not UTF-8"
            ) from exc
        path = root / relative
        if not path.is_file() or path.is_symlink():
            raise FinalReleaseGateError(
                f"release execution path is invalid: {relative}"
            )
        paths.add(relative)
    return tuple(sorted(paths))


def _verify_post_real_readiness(
    *,
    readiness_path: str | Path,
    ledger_path: str | Path,
    require_head: str,
    repo_root: str | Path = _REPO_ROOT,
) -> dict[str, object]:
    root = Path(repo_root).resolve()
    readiness_file = _repository_regular_file(
        root,
        readiness_path,
        label="release readiness",
    )
    readiness = _read_json(readiness_file)
    if (
        readiness.get("schema_version")
        != "guide-task11-release-readiness-v1"
    ):
        raise FinalReleaseGateError(
            "post-real release readiness is invalid"
        )
    task11_commit = _git_commit(
        root,
        str(readiness.get("task11_commit")),
    )
    head = _git_commit(root, require_head)
    current_head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if current_head != head or (
        head != task11_commit
        and _git_parent(root, head) != task11_commit
    ):
        raise FinalReleaseGateError(
            "post-real release ancestry is invalid"
        )
    raw_paths = readiness.get("release_execution_paths")
    raw_hashes = readiness.get(
        "release_execution_blob_sha256_by_path"
    )
    raw_plans = readiness.get("release_plan_paths")
    if (
        not isinstance(raw_paths, list)
        or raw_paths != sorted(set(raw_paths))
        or not isinstance(raw_hashes, dict)
        or set(raw_hashes) != set(raw_paths)
        or not isinstance(raw_plans, list)
        or tuple(raw_plans) != _RELEASE_PLAN_PATHS
        or not set(raw_plans) <= set(raw_paths)
    ):
        raise FinalReleaseGateError(
            "post-real release execution tree is invalid"
        )
    execution_paths = tuple(
        _normalized_release_path(str(item)) for item in raw_paths
    )
    for relative in execution_paths:
        committed = _committed_bytes(
            root,
            revision=task11_commit,
            relative=relative,
        )
        if sha256(committed).hexdigest() != raw_hashes.get(relative):
            raise FinalReleaseGateError(
                "post-real release execution tree is invalid"
            )
    if readiness.get(
        "release_execution_tree_sha256"
    ) != _canonical_committed_payload_sha256(
        root,
        revision=task11_commit,
        paths=execution_paths,
    ):
        raise FinalReleaseGateError(
            "post-real release execution tree is invalid"
        )
    frozen_paths = tuple(
        relative
        for relative in execution_paths
        if relative not in _RELEASE_PLAN_PATHS
    )
    expected_current_paths = tuple(
        relative
        for relative in frozen_paths
        if (
            relative.startswith(("app/", "tools/", "tests/"))
            or relative in _RELEASE_ROOT_FILES
        )
    )
    if _current_execution_paths(root) != expected_current_paths:
        raise FinalReleaseGateError(
            "post-real release execution tree drift"
        )
    for relative in frozen_paths:
        path = root / relative
        if (
            not path.is_file()
            or path.is_symlink()
            or _file_sha256(path) != raw_hashes[relative]
        ):
            raise FinalReleaseGateError(
                "post-real release execution tree drift"
            )
    for relative in _RELEASE_PLAN_PATHS:
        path = root / relative
        if not path.is_file() or path.is_symlink():
            raise FinalReleaseGateError(
                "post-real release plan is invalid"
            )
    evidence_files = readiness.get("evidence_files")
    evidence_hashes = readiness.get("evidence_sha256")
    if (
        not isinstance(evidence_files, dict)
        or not isinstance(evidence_hashes, dict)
        or set(evidence_files) != set(evidence_hashes)
    ):
        raise FinalReleaseGateError(
            "post-real readiness evidence binding is invalid"
        )
    for role, raw_path in evidence_files.items():
        path = _repository_regular_file(
            root,
            str(raw_path),
            label="release evidence",
        )
        if (
            _file_sha256(path) != evidence_hashes.get(role)
        ):
            raise FinalReleaseGateError(
                f"post-real readiness evidence drift: {role}"
            )
    bound_ledger = _repository_regular_file(
        root,
        str(readiness.get("ledger_path")),
        label="release ledger",
    )
    if Path(ledger_path).resolve() != bound_ledger:
        raise FinalReleaseGateError(
            "post-real readiness ledger mismatch"
        )
    try:
        verify_ledger_extension(
            read_ledger(bound_ledger),
            anchor_revision=readiness.get("ledger_anchor_revision"),
            anchor_hash=readiness.get("ledger_anchor_hash"),
        )
    except ValueError as exc:
        raise FinalReleaseGateError(
            "post-real readiness ledger anchor is invalid"
        ) from exc
    return readiness


def _indexed_checksum_directory(
    root: Path,
    directory: Path,
) -> dict[str, str]:
    checksum_path = directory / "SHA256SUMS"
    try:
        lines = checksum_path.read_text(encoding="ascii").splitlines()
    except OSError as exc:
        raise FinalReleaseGateError(
            f"release checksum index is missing: {directory}"
        ) from exc
    indexed: dict[str, str] = {}
    for line in lines:
        digest, separator, relative = line.partition("  ")
        if (
            separator != "  "
            or _SHA256_PATTERN.fullmatch(digest) is None
            or not relative
            or Path(relative).is_absolute()
            or ".." in Path(relative).parts
        ):
            raise FinalReleaseGateError(
                f"release checksum index is invalid: {directory}"
            )
        path = (directory / relative).resolve()
        if (
            directory.resolve() not in path.parents
            or not path.is_file()
            or path.is_symlink()
            or _file_sha256(path) != digest
        ):
            raise FinalReleaseGateError(
                f"release checksum mismatch: {path}"
            )
        normalized = _repository_relative(root, path)
        if normalized in indexed:
            raise FinalReleaseGateError(
                "release checksum index contains duplicates"
            )
        indexed[normalized] = digest
    actual = {
        _repository_relative(root, path)
        for path in directory.rglob("*")
        if path.is_file() and path != checksum_path
    }
    if set(indexed) != actual:
        raise FinalReleaseGateError(
            f"release checksum index omits artifacts: {directory}"
        )
    indexed[_repository_relative(root, checksum_path)] = _file_sha256(
        checksum_path
    )
    return indexed


def _indexed_browser_artifacts(
    *,
    root: Path,
    output: Path,
) -> dict[str, str]:
    summary_path = output / "mainline-browser/summary.json"
    summary = _read_json(summary_path)
    raw_index = summary.get("artifact_sha256")
    if not isinstance(raw_index, dict) or not raw_index:
        raise FinalReleaseGateError(
            "release browser artifact index is invalid"
        )
    indexed: dict[str, str] = {}
    allowed_roots = tuple(
        (output / name).resolve()
        for name in (
            "browser-desktop",
            "browser-mobile",
            "mainline-browser",
        )
    )
    for raw_path, expected in raw_index.items():
        if (
            not isinstance(raw_path, str)
            or _SHA256_PATTERN.fullmatch(str(expected)) is None
        ):
            raise FinalReleaseGateError(
                "release browser artifact index is invalid"
            )
        path = _repository_regular_file(
            root,
            raw_path,
            label="release browser artifact",
        )
        if (
            not any(parent == path or parent in path.parents for parent in allowed_roots)
            or _file_sha256(path) != expected
        ):
            raise FinalReleaseGateError(
                f"release browser artifact mismatch: {raw_path}"
            )
        normalized = _repository_relative(root, path)
        if normalized != raw_path or normalized in indexed:
            raise FinalReleaseGateError(
                "release browser artifact index is invalid"
            )
        indexed[normalized] = str(expected)
    actual = {
        _repository_relative(root, path)
        for parent in allowed_roots
        if parent.is_dir()
        for path in parent.rglob("*")
        if path.is_file() and path.resolve() != summary_path.resolve()
    }
    if set(indexed) != actual:
        raise FinalReleaseGateError(
            "release browser artifact index omits files"
        )
    indexed[_repository_relative(root, summary_path)] = _file_sha256(
        summary_path
    )
    return indexed


def _validate_browser_release_evidence(
    *,
    repo_root: Path,
    output: Path,
    browser_summary: Mapping[str, object],
) -> None:
    _indexed_browser_artifacts(root=repo_root, output=output)
    raw_turns = browser_summary.get("turns")
    counter_keys = (
        "serious_failure_count",
        "frontend_contract_violation_count",
        "wrong_binding_count",
        "unaligned_price_specification_count",
        "copywriter_fallback_count",
        "invalid_clarification_count",
    )
    if not isinstance(raw_turns, list) or len(raw_turns) != 14:
        raise FinalReleaseGateError(
            "release browser turn index is invalid"
        )
    expected_keys = {
        (viewport, mode)
        for viewport in ("desktop", "mobile")
        for mode in _MANUAL_REVIEW_MODES
    }
    seen: set[tuple[str, str]] = set()
    totals = {key: 0 for key in counter_keys}
    mode_contracts = {
        "explore_recommendation": ("recommendation", "explore"),
        "fit_recommendation": ("recommendation", "fit"),
        "product_knowledge": ("product_knowledge", None),
        "comparison": ("comparison", None),
        "image_identity": ("image_identity", None),
        "image_fit_recommendation": ("recommendation", "fit"),
        "image_comparison": ("comparison", None),
    }
    for row in raw_turns:
        if not isinstance(row, dict):
            raise FinalReleaseGateError(
                "release browser turn index is invalid"
            )
        viewport = row.get("viewport")
        mode = row.get("mode")
        turn_id = row.get("turn_id")
        raw_directory = row.get("directory")
        key = (viewport, mode)
        if (
            key not in expected_keys
            or key in seen
            or not isinstance(turn_id, str)
            or not turn_id
            or not isinstance(raw_directory, str)
        ):
            raise FinalReleaseGateError(
                "release browser turn index is invalid"
            )
        directory = (output / raw_directory).resolve()
        viewport_root = (output / f"browser-{viewport}").resolve()
        if (
            viewport_root not in directory.parents
            or _repository_relative(repo_root, directory)
            != _normalized_release_path(
                str((output / raw_directory).relative_to(repo_root))
            )
        ):
            raise FinalReleaseGateError(
                "release browser turn directory is invalid"
            )
        try:
            validate_audit_bundle(
                directory,
                expected_turn_id=turn_id,
            )
            derived = derive_release_turn_counters(directory)
        except (AuditBundleError, OSError, UnicodeError) as exc:
            raise FinalReleaseGateError(
                f"release browser turn evidence is invalid: {turn_id}"
            ) from exc
        declared = row.get("release_counters")
        if declared is not None and declared != derived:
            raise FinalReleaseGateError(
                "release browser turn counters are not derived"
            )
        contract = _read_json(
            directory / "presentation-contract.json"
        )
        expected_contract_mode, expected_recommendation_mode = (
            mode_contracts[str(mode)]
        )
        if (
            contract.get("mode") != expected_contract_mode
            or (
                expected_recommendation_mode is not None
                and contract.get("recommendation_mode")
                != expected_recommendation_mode
            )
        ):
            raise FinalReleaseGateError(
                "release browser mode binding is invalid"
            )
        for counter in counter_keys:
            totals[counter] += derived[counter]
        seen.add((str(viewport), str(mode)))
    if (
        seen != expected_keys
        or browser_summary.get("turn_count") != 14
        or browser_summary.get("passed") is not True
        or any(
            browser_summary.get(key) != value
            for key, value in totals.items()
        )
        or any(totals.values())
    ):
        raise FinalReleaseGateError(
            "release browser counters are not derived"
        )


def _worktree_status(
    root: Path,
) -> dict[str, str]:
    output = subprocess.run(
        [
            "git",
            "status",
            "--porcelain=v1",
            "-z",
            "--untracked-files=all",
        ],
        cwd=root,
        check=True,
        capture_output=True,
    ).stdout
    records = [item for item in output.split(b"\0") if item]
    statuses: dict[str, str] = {}
    for record in records:
        text = record.decode("utf-8")
        if len(text) < 4:
            raise FinalReleaseGateError(
                "release worktree status is invalid"
            )
        code = text[:2]
        path = text[3:]
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        normalized = _normalized_release_path(path)
        statuses[normalized] = (
            "A"
            if code == "??" or "A" in code
            else ("D" if "D" in code else "M")
        )
    return statuses


def _normalized_release_path(value: str) -> str:
    path = Path(value)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise FinalReleaseGateError("release path is invalid")
    return path.as_posix()


def build_evidence_manifest(
    *,
    attempt_context_path: str | Path,
    readiness_path: str | Path,
    ledger_path: str | Path,
    plan_paths: Sequence[str | Path],
    output_path: str | Path,
    repo_root: str | Path = _REPO_ROOT,
) -> dict[str, object]:
    root = Path(repo_root).resolve()
    context_path = Path(attempt_context_path).resolve()
    current_head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    context, output, bound_ledger, ledger, readiness = (
        _verified_post_real_context(
        attempt_context_path=context_path,
        expected_tail_phase="browser",
        require_head=current_head,
        require_task11_head=True,
        repo_root=root,
        )
    )
    if (
        Path(readiness_path).resolve()
        != Path(str(context.get("readiness_path"))).resolve()
        or Path(ledger_path).resolve() != bound_ledger
    ):
        raise FinalReleaseGateError(
            "release manifest context binding is invalid"
        )
    phase_ids = context["phase_attempt_ids"]
    translation_attempt = _attempt(
        ledger,
        attempt_id=phase_ids.get("translation"),
    )
    browser_attempt = _attempt(
        ledger,
        attempt_id=phase_ids.get("browser"),
    )
    if (
        translation_attempt.get("result") != "passed"
        or browser_attempt.get("result") != "passed"
    ):
        raise FinalReleaseGateError(
            "release manifest requires passed attempt chain"
        )
    translation_context = Path(
        str(translation_attempt.get("context_path"))
    ).resolve()
    translation_output = translation_context.parent
    fixed = (
        translation_context,
        context_path,
        translation_output / "focused.json",
        output / "manual-screenshot-review.json",
        output / "release-summary.json",
        Path(readiness_path).resolve(),
        Path(ledger_path).resolve(),
    )
    artifacts: dict[str, str] = {}
    for path in fixed:
        if not path.is_file() or path.is_symlink():
            raise FinalReleaseGateError(
                f"release artifact is missing: {path}"
            )
        artifacts[_repository_relative(root, path)] = _file_sha256(path)
    for directory in (
        translation_output / "real-translation",
        translation_output / "real-backend",
    ):
        artifacts.update(_indexed_checksum_directory(root, directory))
    artifacts.update(
        _indexed_browser_artifacts(root=root, output=output)
    )
    runtime_identity = output / "runtime-identity.json"
    if not runtime_identity.is_file() or runtime_identity.is_symlink():
        raise FinalReleaseGateError(
            "release runtime identity is missing"
        )
    artifacts[_repository_relative(root, runtime_identity)] = (
        _file_sha256(runtime_identity)
    )
    normalized_plans = tuple(
        sorted(
            _repository_relative(root, Path(path).resolve())
            for path in plan_paths
        )
    )
    if normalized_plans != _RELEASE_PLAN_PATHS:
        raise FinalReleaseGateError(
            "release manifest requires exactly two plans"
        )
    for relative in normalized_plans:
        path = root / relative
        if not path.is_file() or path.is_symlink():
            raise FinalReleaseGateError(
                "release plan is unavailable"
            )
        artifacts[relative] = _file_sha256(path)
    actual_attempt_files = {
        _repository_relative(root, path)
        for parent in (translation_output, output)
        for path in parent.rglob("*")
        if path.is_file()
    }
    if not actual_attempt_files <= set(artifacts):
        raise FinalReleaseGateError(
            "release attempt contains unindexed artifacts"
        )
    manifest_path = Path(output_path).resolve()
    manifest_relative = _repository_relative(root, manifest_path)
    if manifest_path.exists() or manifest_path.is_symlink():
        raise FinalReleaseGateError(
            "release evidence manifest already exists"
        )
    status = _worktree_status(root)
    if set(status) != set(artifacts):
        raise FinalReleaseGateError(
            "post-real closure contains undeclared changes"
        )
    expected_status = {
        path: status.get(path)
        for path in artifacts
    }
    if any(value not in {"A", "M", "D"} for value in expected_status.values()):
        raise FinalReleaseGateError(
            "release artifact has no pending Git change"
        )
    expected_status[manifest_relative] = "A"
    anchor = ledger_anchor(ledger)
    manifest: dict[str, object] = {
        "schema_version": "guide-release-evidence-manifest-v1",
        "plan_revision": readiness.get("plan_revision"),
        "task11_commit": readiness.get("task11_commit"),
        "attempt_context_path": _repository_relative(root, context_path),
        "attempt_context_sha256": _file_sha256(context_path),
        "readiness_path": _repository_relative(
            root,
            Path(readiness_path).resolve(),
        ),
        "readiness_sha256": _file_sha256(
            Path(readiness_path).resolve()
        ),
        "ledger_path": _repository_relative(
            root,
            Path(ledger_path).resolve(),
        ),
        "ledger_revision": anchor["revision"],
        "ledger_hash": anchor["revision_hash"],
        "plan_paths": list(normalized_plans),
        "artifact_sha256_by_path": dict(sorted(artifacts.items())),
        "approved_paths": sorted({
            *artifacts,
            manifest_relative,
        }),
        "expected_name_status": dict(sorted(expected_status.items())),
        "payload_sha256": _canonical_payload_sha256(
            root,
            tuple(artifacts),
        ),
    }
    _write_json_exclusive(manifest_path, manifest)
    return manifest


def _validated_evidence_manifest(
    *,
    manifest_path: Path,
    repo_root: Path,
) -> dict[str, object]:
    manifest = _read_json(manifest_path)
    artifacts = manifest.get("artifact_sha256_by_path")
    approved = manifest.get("approved_paths")
    expected_status = manifest.get("expected_name_status")
    manifest_relative = _repository_relative(repo_root, manifest_path)
    if (
        manifest.get("schema_version")
        != "guide-release-evidence-manifest-v1"
        or not isinstance(artifacts, dict)
        or not artifacts
        or not isinstance(approved, list)
        or approved != sorted(set(approved))
        or set(approved) != {*artifacts, manifest_relative}
        or not isinstance(expected_status, dict)
        or set(expected_status) != set(approved)
        or expected_status.get(manifest_relative) != "A"
    ):
        raise FinalReleaseGateError(
            "release evidence manifest is invalid"
        )
    for relative, expected in artifacts.items():
        path = repo_root / _normalized_release_path(str(relative))
        if (
            not path.is_file()
            or path.is_symlink()
            or expected != _file_sha256(path)
        ):
            raise FinalReleaseGateError(
                f"release evidence hash mismatch: {relative}"
            )
    if manifest.get("payload_sha256") != _canonical_payload_sha256(
        repo_root,
        tuple(str(path) for path in artifacts),
    ):
        raise FinalReleaseGateError(
            "release evidence payload hash mismatch"
        )
    ledger_path = repo_root / str(manifest.get("ledger_path"))
    anchor = ledger_anchor(read_ledger(ledger_path))
    if (
        anchor["revision"] != manifest.get("ledger_revision")
        or anchor["revision_hash"] != manifest.get("ledger_hash")
    ):
        raise FinalReleaseGateError(
            "release evidence ledger tip drift"
        )
    return manifest


def _staged_status(root: Path) -> dict[str, str]:
    output = subprocess.run(
        [
            "git",
            "diff",
            "--cached",
            "--name-status",
            "--no-renames",
            "-z",
        ],
        cwd=root,
        check=True,
        capture_output=True,
    ).stdout
    fields = [
        item.decode("utf-8")
        for item in output.split(b"\0")
        if item
    ]
    if len(fields) % 2:
        raise FinalReleaseGateError(
            "staged release status is invalid"
        )
    return {
        fields[index + 1]: fields[index]
        for index in range(0, len(fields), 2)
    }


def stage_evidence(
    *,
    manifest_path: str | Path,
    repo_root: str | Path = _REPO_ROOT,
) -> None:
    root = Path(repo_root).resolve()
    path = Path(manifest_path).resolve()
    manifest = _validated_evidence_manifest(
        manifest_path=path,
        repo_root=root,
    )
    if _staged_status(root):
        raise FinalReleaseGateError(
            "release staging requires an empty index"
        )
    for relative in manifest["approved_paths"]:
        subprocess.run(
            ["git", "add", "-A", "--", str(relative)],
            cwd=root,
            check=True,
        )
    verify_evidence_staging(
        manifest_path=path,
        repo_root=root,
    )


def verify_evidence_staging(
    *,
    manifest_path: str | Path,
    repo_root: str | Path = _REPO_ROOT,
) -> dict[str, object]:
    root = Path(repo_root).resolve()
    path = Path(manifest_path).resolve()
    manifest = _validated_evidence_manifest(
        manifest_path=path,
        repo_root=root,
    )
    staged = _staged_status(root)
    if staged != manifest["expected_name_status"]:
        raise FinalReleaseGateError(
            "release staged path or status mismatch"
        )
    for relative, expected in manifest[
        "artifact_sha256_by_path"
    ].items():
        blob = subprocess.run(
            ["git", "show", f":{relative}"],
            cwd=root,
            check=False,
            capture_output=True,
        )
        if blob.returncode != 0 or sha256(blob.stdout).hexdigest() != expected:
            raise FinalReleaseGateError(
                f"staged release artifact mismatch: {relative}"
            )
    manifest_relative = _repository_relative(root, path)
    manifest_blob = subprocess.run(
        ["git", "show", f":{manifest_relative}"],
        cwd=root,
        check=False,
        capture_output=True,
    )
    if manifest_blob.returncode != 0 or manifest_blob.stdout != path.read_bytes():
        raise FinalReleaseGateError(
            "staged release manifest mismatch"
        )
    return {"passed": True, "approved_path_count": len(staged)}


def _git_commit(root: Path, revision: str) -> str:
    if _COMMIT_PATTERN.fullmatch(revision) is None:
        raise FinalReleaseGateError("release commit is invalid")
    completed = subprocess.run(
        ["git", "rev-parse", "--verify", f"{revision}^{{commit}}"],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0 or completed.stdout.strip() != revision:
        raise FinalReleaseGateError("release commit is invalid")
    return revision


def _git_parent(root: Path, revision: str) -> str:
    row = subprocess.run(
        ["git", "rev-list", "--parents", "-n", "1", revision],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip().split()
    if len(row) != 2 or row[0] != revision:
        raise FinalReleaseGateError(
            "release commit must have exactly one parent"
        )
    return row[1]


def _git_diff_status(
    root: Path,
    *,
    base: str,
    revision: str,
) -> dict[str, str]:
    output = subprocess.run(
        [
            "git",
            "diff",
            "--name-status",
            "--no-renames",
            "-z",
            base,
            revision,
        ],
        cwd=root,
        check=True,
        capture_output=True,
    ).stdout
    fields = [
        item.decode("utf-8")
        for item in output.split(b"\0")
        if item
    ]
    if len(fields) % 2:
        raise FinalReleaseGateError("release commit diff is invalid")
    return {
        fields[index + 1]: fields[index]
        for index in range(0, len(fields), 2)
    }


def _committed_bytes(
    root: Path,
    *,
    revision: str,
    relative: str,
) -> bytes:
    completed = subprocess.run(
        ["git", "show", f"{revision}:{relative}"],
        cwd=root,
        check=False,
        capture_output=True,
    )
    if completed.returncode != 0:
        raise FinalReleaseGateError(
            f"committed release artifact is missing: {relative}"
        )
    return completed.stdout


def _unique_plan_line(
    lines: Sequence[str],
    pattern: re.Pattern[str],
) -> tuple[int, re.Match[str]]:
    matches = [
        (index, match)
        for index, line in enumerate(lines)
        if (match := pattern.fullmatch(line)) is not None
    ]
    if len(matches) != 1:
        raise FinalReleaseGateError(
            "release plan structure is invalid"
        )
    return matches[0]


def _release_closure_record(
    *,
    seal: Mapping[str, object],
    seal_relative: str,
    seal_sha256: str,
) -> tuple[str, ...]:
    fields = {
        "task11_commit": seal.get("task11_commit"),
        "attempt_context_path": seal.get("attempt_context_path"),
        "evidence_commit": seal.get("evidence_commit"),
        "release_summary_path": seal.get("release_summary_path"),
        "release_summary_sha256": seal.get("release_summary_sha256"),
        "manual_screenshot_review_path": seal.get(
            "manual_screenshot_review_path"
        ),
        "manual_screenshot_review_sha256": seal.get(
            "manual_screenshot_review_sha256"
        ),
    }
    if (
        any(
            not isinstance(value, str) or not value
            for value in fields.values()
        )
        or _SHA256_PATTERN.fullmatch(seal_sha256) is None
    ):
        raise FinalReleaseGateError(
            "release plan closure record is invalid"
        )
    return (
        "## Final Release Closure Record",
        "- [x] Task 12 Step 9 complete",
        f"Task 11 commit: {fields['task11_commit']}",
        f"Attempt context: {fields['attempt_context_path']}",
        f"Evidence commit: {fields['evidence_commit']}",
        f"Release summary path: {fields['release_summary_path']}",
        (
            "Release summary SHA-256: "
            f"{fields['release_summary_sha256']}"
        ),
        (
            "Manual review path: "
            f"{fields['manual_screenshot_review_path']}"
        ),
        (
            "Manual review SHA-256: "
            f"{fields['manual_screenshot_review_sha256']}"
        ),
        f"Release seal path: {seal_relative}",
        f"Release seal SHA-256: {seal_sha256}",
    )


def _validate_release_plan_closure(
    *,
    evidence_text: str,
    final_text: str,
    seal: Mapping[str, object],
    seal_relative: str,
    seal_sha256: str,
) -> None:
    evidence_lines = evidence_text.splitlines()
    final_lines = final_text.splitlines()
    record = _release_closure_record(
        seal=seal,
        seal_relative=seal_relative,
        seal_sha256=seal_sha256,
    )
    record_indexes = [
        index
        for index, line in enumerate(final_lines)
        if line == record[0]
    ]
    if (
        record[0] in evidence_lines
        or len(record_indexes) != 1
        or tuple(final_lines[record_indexes[0]:]) != record
    ):
        raise FinalReleaseGateError(
            "release plan closure record is invalid"
        )
    final_prefix = final_lines[:record_indexes[0]]
    if final_prefix[-1:] == [""]:
        final_prefix = final_prefix[:-1]

    status_patterns = (
        (
            re.compile(r"^Task 11(?: status)?: completed$"),
            re.compile(r"^Task 11(?: status)?: completed$"),
        ),
        (
            re.compile(
                r"^Task 12(?: status)?: (?!completed$).+$"
            ),
            re.compile(r"^Task 12(?: status)?: completed$"),
        ),
        (
            re.compile(r"^Release status: READY_TO_SEAL$"),
            re.compile(r"^Release status: READY$"),
        ),
    )
    evidence_normalized = list(evidence_lines)
    final_normalized = list(final_prefix)
    for ordinal, (evidence_pattern, final_pattern) in enumerate(
        status_patterns,
        start=1,
    ):
        evidence_index, _ = _unique_plan_line(
            evidence_lines,
            evidence_pattern,
        )
        final_index, _ = _unique_plan_line(
            final_prefix,
            final_pattern,
        )
        token = f"<RELEASE_STATUS_{ordinal}>"
        evidence_normalized[evidence_index] = token
        final_normalized[final_index] = token

    for task in ("11", "12"):
        evidence_index, evidence_match = _unique_plan_line(
            evidence_lines,
            re.compile(
                rf"^(#{{2,6}}) (Task {task}(?:[ :(].*)?)$"
            ),
        )
        final_index, final_match = _unique_plan_line(
            final_prefix,
            re.compile(
                rf"^(#{{2,6}}) ~~(Task {task}(?:[ :(].*)?)~~$"
            ),
        )
        if evidence_match.groups() != final_match.groups():
            raise FinalReleaseGateError(
                "release plan structure is invalid"
            )
        token = f"<TASK_{task}_HEADING>"
        evidence_normalized[evidence_index] = token
        final_normalized[final_index] = token

    evidence_step_index, evidence_step = _unique_plan_line(
        evidence_lines,
        re.compile(r"^(\s*-\s*)\[ \](\s+\*\*Step 9:.*\*\*)$"),
    )
    final_step_index, final_step = _unique_plan_line(
        final_prefix,
        re.compile(r"^(\s*-\s*)\[x\](\s+\*\*Step 9:.*\*\*)$"),
    )
    if evidence_step.groups() != final_step.groups():
        raise FinalReleaseGateError(
            "release plan structure is invalid"
        )
    evidence_normalized[evidence_step_index] = "<TASK_12_STEP_9>"
    final_normalized[final_step_index] = "<TASK_12_STEP_9>"
    if evidence_normalized != final_normalized:
        raise FinalReleaseGateError(
            "release plan closure diff is invalid"
        )


def create_release_seal(
    *,
    attempt_context_path: str | Path,
    evidence_commit: str,
    output_path: str | Path,
    repo_root: str | Path = _REPO_ROOT,
) -> dict[str, object]:
    root = Path(repo_root).resolve()
    context_path = Path(attempt_context_path).resolve()
    commit = _git_commit(root, evidence_commit)
    if subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip() != commit:
        raise FinalReleaseGateError(
            "evidence commit must equal HEAD"
        )
    context, output, _, _, readiness = _verified_post_real_context(
        attempt_context_path=context_path,
        expected_tail_phase="browser",
        require_head=commit,
        require_task11_head=False,
        repo_root=root,
    )
    readiness_path = Path(str(context.get("readiness_path"))).resolve()
    task11_commit = _git_commit(
        root,
        str(readiness.get("task11_commit")),
    )
    if _git_parent(root, commit) != task11_commit:
        raise FinalReleaseGateError(
            "evidence commit must directly follow Task 11"
        )
    manifest_path = (
        root
        / "docs/audits/final-release/mainline-contract-closure/"
        "release-evidence-manifest.json"
    )
    manifest = _validated_evidence_manifest(
        manifest_path=manifest_path,
        repo_root=root,
    )
    manifest_relative = _repository_relative(root, manifest_path)
    if (
        manifest.get("schema_version")
        != "guide-release-evidence-manifest-v1"
        or manifest.get("task11_commit") != task11_commit
        or manifest.get("attempt_context_path")
        != _repository_relative(root, context_path)
        or manifest.get("attempt_context_sha256")
        != _file_sha256(context_path)
        or manifest.get("readiness_path")
        != _repository_relative(root, readiness_path)
        or manifest.get("readiness_sha256")
        != _file_sha256(readiness_path)
        or manifest.get("ledger_path")
        != _repository_relative(
            root,
            Path(str(context.get("ledger_path"))).resolve(),
        )
        or _committed_bytes(
            root,
            revision=commit,
            relative=manifest_relative,
        )
        != manifest_path.read_bytes()
    ):
        raise FinalReleaseGateError(
            "release evidence manifest binding is invalid"
        )
    committed_status = _git_diff_status(
        root,
        base=task11_commit,
        revision=commit,
    )
    if committed_status != manifest.get("expected_name_status"):
        raise FinalReleaseGateError(
            "evidence commit path or status set is invalid"
        )
    for relative, expected_hash in manifest[
        "artifact_sha256_by_path"
    ].items():
        if sha256(
            _committed_bytes(
                root,
                revision=commit,
                relative=str(relative),
            )
        ).hexdigest() != expected_hash:
            raise FinalReleaseGateError(
                f"evidence commit artifact drift: {relative}"
            )
    if _worktree_status(root):
        raise FinalReleaseGateError(
            "release seal creation requires a clean worktree"
        )
    summary_path = output / "release-summary.json"
    manual_path = output / "manual-screenshot-review.json"
    _validate_sealed_release_evidence(
        context_path=context_path,
        readiness_path=readiness_path,
        summary_path=summary_path,
        manual_path=manual_path,
        repo_root=root,
    )
    summary = _read_json(summary_path)
    manual = _read_json(manual_path)
    if summary.get("passed") is not True or manual.get("passed") is not True:
        raise FinalReleaseGateError(
            "release evidence is not passed"
        )
    seal: dict[str, object] = {
        "schema_version": "guide-release-seal-v1",
        "passed": True,
        "plan_revision": readiness.get("plan_revision"),
        "task11_commit": task11_commit,
        "evidence_commit": commit,
        "attempt_context_path": _repository_relative(root, context_path),
        "attempt_context_sha256": _file_sha256(context_path),
        "release_readiness_path": _repository_relative(
            root,
            readiness_path,
        ),
        "release_readiness_sha256": _file_sha256(readiness_path),
        "release_evidence_manifest_path": manifest_relative,
        "release_evidence_manifest_sha256": _file_sha256(manifest_path),
        "release_summary_path": _repository_relative(root, summary_path),
        "release_summary_sha256": _file_sha256(summary_path),
        "manual_screenshot_review_path": _repository_relative(
            root,
            manual_path,
        ),
        "manual_screenshot_review_sha256": _file_sha256(manual_path),
    }
    _write_json_exclusive(Path(output_path).resolve(), seal)
    return seal


def _validated_committed_evidence_manifest(
    *,
    manifest_path: Path,
    evidence_commit: str,
    task11_commit: str,
    repo_root: Path,
) -> dict[str, object]:
    manifest_relative = _repository_relative(repo_root, manifest_path)
    committed = _committed_bytes(
        repo_root,
        revision=evidence_commit,
        relative=manifest_relative,
    )
    if committed != manifest_path.read_bytes():
        raise FinalReleaseGateError(
            "release evidence manifest commit binding is invalid"
        )
    try:
        manifest = json.loads(committed)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FinalReleaseGateError(
            "release evidence manifest is invalid"
        ) from exc
    if not isinstance(manifest, dict):
        raise FinalReleaseGateError(
            "release evidence manifest is invalid"
        )
    artifacts = manifest.get("artifact_sha256_by_path")
    approved = manifest.get("approved_paths")
    expected_status = manifest.get("expected_name_status")
    if (
        manifest.get("schema_version")
        != "guide-release-evidence-manifest-v1"
        or manifest.get("task11_commit") != task11_commit
        or not isinstance(artifacts, dict)
        or not artifacts
        or not isinstance(approved, list)
        or approved != sorted(set(approved))
        or set(approved) != {*artifacts, manifest_relative}
        or not isinstance(expected_status, dict)
        or set(expected_status) != set(approved)
        or expected_status.get(manifest_relative) != "A"
        or _git_diff_status(
            repo_root,
            base=task11_commit,
            revision=evidence_commit,
        )
        != expected_status
    ):
        raise FinalReleaseGateError(
            "release evidence manifest is invalid"
        )
    normalized_artifacts: dict[str, str] = {}
    for raw_relative, expected in artifacts.items():
        relative = _normalized_release_path(str(raw_relative))
        if (
            relative != raw_relative
            or relative in normalized_artifacts
            or _SHA256_PATTERN.fullmatch(str(expected)) is None
            or sha256(
                _committed_bytes(
                    repo_root,
                    revision=evidence_commit,
                    relative=relative,
                )
            ).hexdigest()
            != expected
        ):
            raise FinalReleaseGateError(
                f"release evidence commit artifact drift: {raw_relative}"
            )
        normalized_artifacts[relative] = str(expected)
    if manifest.get(
        "payload_sha256"
    ) != _canonical_committed_payload_sha256(
        repo_root,
        revision=evidence_commit,
        paths=tuple(normalized_artifacts),
    ):
        raise FinalReleaseGateError(
            "release evidence manifest payload is invalid"
        )
    ledger_relative = _normalized_release_path(
        str(manifest.get("ledger_path"))
    )
    if ledger_relative not in normalized_artifacts:
        raise FinalReleaseGateError(
            "release evidence manifest ledger binding is invalid"
        )
    ledger_path = _repository_regular_file(
        repo_root,
        ledger_relative,
        label="release evidence ledger",
    )
    anchor = ledger_anchor(read_ledger(ledger_path))
    if (
        anchor["revision"] != manifest.get("ledger_revision")
        or anchor["revision_hash"] != manifest.get("ledger_hash")
    ):
        raise FinalReleaseGateError(
            "release evidence manifest ledger binding is invalid"
        )
    return manifest


def _sealed_evidence_file(
    *,
    seal: Mapping[str, object],
    path_key: str,
    hash_key: str,
    label: str,
    manifest: Mapping[str, object],
    evidence_commit: str,
    repo_root: Path,
) -> Path:
    raw_path = seal.get(path_key)
    expected = seal.get(hash_key)
    if (
        not isinstance(raw_path, str)
        or _SHA256_PATTERN.fullmatch(str(expected)) is None
    ):
        raise FinalReleaseGateError(f"{label} seal binding is invalid")
    path = _repository_regular_file(
        repo_root,
        raw_path,
        label=label,
    )
    relative = _repository_relative(repo_root, path)
    artifacts = manifest.get("artifact_sha256_by_path")
    if (
        not isinstance(artifacts, dict)
        or artifacts.get(relative) != expected
        or _file_sha256(path) != expected
        or sha256(
            _committed_bytes(
                repo_root,
                revision=evidence_commit,
                relative=relative,
            )
        ).hexdigest()
        != expected
    ):
        raise FinalReleaseGateError(f"{label} seal binding is invalid")
    return path


def _validate_manual_review_rows(
    *,
    repo_root: Path,
    output: Path,
    browser_summary: Mapping[str, object],
    manual_review: Mapping[str, object],
) -> None:
    raw_turns = browser_summary.get("turns")
    raw_rows = manual_review.get("rows")
    if (
        not isinstance(raw_turns, list)
        or not isinstance(raw_rows, list)
        or len(raw_rows) != 14
    ):
        raise FinalReleaseGateError(
            "manual screenshot review rows are invalid"
        )
    turn_directories: dict[tuple[str, str], tuple[Path, str]] = {}
    for turn in raw_turns:
        if not isinstance(turn, dict):
            raise FinalReleaseGateError(
                "manual screenshot review rows are invalid"
            )
        key = (turn.get("viewport"), turn.get("mode"))
        raw_directory = turn.get("directory")
        turn_id = turn.get("turn_id")
        if (
            key in turn_directories
            or key[0] not in {"desktop", "mobile"}
            or key[1] not in _MANUAL_REVIEW_MODES
            or not isinstance(raw_directory, str)
            or not isinstance(turn_id, str)
            or not turn_id
        ):
            raise FinalReleaseGateError(
                "manual screenshot review rows are invalid"
            )
        relative_directory = Path(raw_directory)
        directory = (output / relative_directory).resolve()
        if (
            relative_directory.is_absolute()
            or ".." in relative_directory.parts
            or len(relative_directory.parts) != 3
            or relative_directory.parts[0] != f"browser-{key[0]}"
            or output not in directory.parents
            or directory
            != (output / relative_directory).absolute()
            or not directory.is_dir()
        ):
            raise FinalReleaseGateError(
                "manual screenshot review rows are invalid"
            )
        turn_directories[(str(key[0]), str(key[1]))] = (
            directory,
            turn_id,
        )

    expected_keys = {
        (viewport, mode)
        for viewport in ("desktop", "mobile")
        for mode in _MANUAL_REVIEW_MODES
    }
    indexed = browser_summary.get("artifact_sha256")
    if (
        set(turn_directories) != expected_keys
        or not isinstance(indexed, dict)
    ):
        raise FinalReleaseGateError(
            "manual screenshot review rows are invalid"
        )
    seen: set[tuple[str, str]] = set()
    for row in raw_rows:
        if not isinstance(row, dict):
            raise FinalReleaseGateError(
                "manual screenshot review rows are invalid"
            )
        key = (row.get("viewport"), row.get("mode"))
        if (
            key not in expected_keys
            or key in seen
            or row.get("verdict") != "passed"
            or row.get("issue_codes") != []
            or not isinstance(row.get("reviewer_id"), str)
            or not str(row.get("reviewer_id")).strip()
            or not isinstance(row.get("reviewed_at"), str)
            or not str(row.get("reviewed_at")).strip()
        ):
            raise FinalReleaseGateError(
                "manual screenshot review rows are invalid"
            )
        directory, turn_id = turn_directories[
            (str(key[0]), str(key[1]))
        ]
        if row.get("turn_id") != turn_id:
            raise FinalReleaseGateError(
                "manual screenshot review turn binding is invalid"
            )
        for name, path_key, hash_key in (
            (
                "screenshot.png",
                "screenshot_path",
                "screenshot_sha256",
            ),
            (
                "presentation-contract.json",
                "presentation_contract_path",
                "presentation_contract_sha256",
            ),
        ):
            path = directory / name
            relative = _repository_relative(repo_root, path)
            digest = _file_sha256(path)
            if (
                row.get("artifact_directory")
                != _repository_relative(repo_root, directory)
                or row.get(path_key) != relative
                or row.get(hash_key) != digest
                or indexed.get(relative) != digest
            ):
                raise FinalReleaseGateError(
                    "manual screenshot review artifact binding is invalid"
                )
        seen.add((str(key[0]), str(key[1])))
    if seen != expected_keys:
        raise FinalReleaseGateError(
            "manual screenshot review rows are invalid"
        )


def _validate_sealed_release_evidence(
    *,
    context_path: Path,
    readiness_path: Path,
    summary_path: Path,
    manual_path: Path,
    repo_root: Path,
) -> None:
    raw_context = _read_json(context_path)
    ledger_path = _repository_regular_file(
        repo_root,
        str(raw_context.get("ledger_path")),
        label="sealed release ledger",
    )
    if (
        Path(str(raw_context.get("readiness_path"))).resolve()
        != readiness_path
    ):
        raise FinalReleaseGateError(
            "sealed release readiness binding is invalid"
        )
    try:
        context = read_attempt_context(
            context_path,
            ledger_path=ledger_path,
            readiness_path=readiness_path,
        )
    except ValueError as exc:
        raise FinalReleaseGateError(
            "sealed release attempt context is invalid"
        ) from exc
    phase_ids = context.get("phase_attempt_ids")
    if (
        not isinstance(phase_ids, dict)
        or attempt_context_phase(context) != "browser"
    ):
        raise FinalReleaseGateError(
            "sealed release attempt context is invalid"
        )
    ledger = read_ledger(ledger_path)
    translation_attempt = _attempt(
        ledger,
        attempt_id=phase_ids.get("translation"),
    )
    browser_attempt = _attempt(
        ledger,
        attempt_id=phase_ids.get("browser"),
    )
    if (
        translation_attempt.get("trajectory_set") != "translation"
        or translation_attempt.get("result") != "passed"
        or browser_attempt.get("trajectory_set") != "browser"
        or browser_attempt.get("result") != "passed"
        or browser_attempt.get("context_path") != str(context_path)
    ):
        raise FinalReleaseGateError(
            "sealed release attempt chain is invalid"
        )
    translation_context = _repository_regular_file(
        repo_root,
        str(translation_attempt.get("context_path")),
        label="translation attempt context",
    )
    translation_output = translation_context.parent
    output = context_path.parent
    focused_path = translation_output / "focused.json"
    translation_directory = translation_output / "real-translation"
    backend_directory = translation_output / "real-backend"
    browser_summary_path = output / "mainline-browser/summary.json"
    focused = _read_json(focused_path)
    translation = _read_json(translation_directory / "summary.json")
    backend = _read_json(backend_directory / "summary.json")
    browser = _read_json(browser_summary_path)
    manual = _read_json(manual_path)
    _validate_aggregate_bindings(
        repo_root=repo_root,
        context_path=context_path,
        context=context,
        readiness_path=readiness_path,
        focused_path=focused_path,
        translation_directory=translation_directory,
        translation_summary=translation,
        backend_directory=backend_directory,
        backend_summary=backend,
        browser_summary_path=browser_summary_path,
        browser_summary=browser,
        manual_review=manual,
        browser_attempt=browser_attempt,
    )
    _validate_manual_review_rows(
        repo_root=repo_root,
        output=output,
        browser_summary=browser,
        manual_review=manual,
    )
    expected = aggregate_release_gate(
        focused=focused,
        translation=translation,
        backend=backend,
        browser=browser,
        manual_review=manual,
    )
    actual = _read_json(summary_path)
    if actual != expected or actual.get("passed") is not True:
        raise FinalReleaseGateError(
            "release summary is not the derived aggregate"
        )


def verify_release_seal(
    *,
    seal_path: str | Path,
    head: str,
    expected_evidence_commit: str,
    repo_root: str | Path = _REPO_ROOT,
) -> dict[str, object]:
    root = Path(repo_root).resolve()
    commit = _git_commit(root, head)
    evidence_commit = _git_commit(root, expected_evidence_commit)
    if (
        subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        != commit
        or _git_parent(root, commit) != evidence_commit
    ):
        raise FinalReleaseGateError(
            "release seal commit ancestry is invalid"
        )
    path = Path(seal_path).resolve()
    seal = _read_json(path)
    seal_relative = _repository_relative(root, path)
    if (
        seal.get("schema_version") != "guide-release-seal-v1"
        or seal.get("passed") is not True
        or seal.get("evidence_commit") != evidence_commit
        or _committed_bytes(
            root,
            revision=commit,
            relative=seal_relative,
        )
        != path.read_bytes()
    ):
        raise FinalReleaseGateError("release seal is invalid")
    final_status = _git_diff_status(
        root,
        base=evidence_commit,
        revision=commit,
    )
    if final_status != {
        _RELEASE_PLAN_PATHS[0]: "M",
        _RELEASE_PLAN_PATHS[1]: "M",
        seal_relative: "A",
    }:
        raise FinalReleaseGateError(
            "release seal commit path set is invalid"
        )
    task11_commit = _git_commit(
        root,
        str(seal.get("task11_commit")),
    )
    if _git_parent(root, evidence_commit) != task11_commit:
        raise FinalReleaseGateError(
            "release evidence ancestry is invalid"
        )
    raw_manifest_path = seal.get("release_evidence_manifest_path")
    if not isinstance(raw_manifest_path, str):
        raise FinalReleaseGateError(
            "release evidence manifest seal binding is invalid"
        )
    manifest_path = _repository_regular_file(
        root,
        raw_manifest_path,
        label="release evidence manifest",
    )
    if (
        _SHA256_PATTERN.fullmatch(
            str(seal.get("release_evidence_manifest_sha256"))
        )
        is None
        or _file_sha256(manifest_path)
        != seal.get("release_evidence_manifest_sha256")
    ):
        raise FinalReleaseGateError(
            "release evidence manifest seal binding is invalid"
        )
    manifest = _validated_committed_evidence_manifest(
        manifest_path=manifest_path,
        evidence_commit=evidence_commit,
        task11_commit=task11_commit,
        repo_root=root,
    )
    context_path = _sealed_evidence_file(
        seal=seal,
        path_key="attempt_context_path",
        hash_key="attempt_context_sha256",
        label="release attempt context",
        manifest=manifest,
        evidence_commit=evidence_commit,
        repo_root=root,
    )
    readiness_path = _sealed_evidence_file(
        seal=seal,
        path_key="release_readiness_path",
        hash_key="release_readiness_sha256",
        label="release readiness",
        manifest=manifest,
        evidence_commit=evidence_commit,
        repo_root=root,
    )
    summary_path = _sealed_evidence_file(
        seal=seal,
        path_key="release_summary_path",
        hash_key="release_summary_sha256",
        label="release summary",
        manifest=manifest,
        evidence_commit=evidence_commit,
        repo_root=root,
    )
    manual_path = _sealed_evidence_file(
        seal=seal,
        path_key="manual_screenshot_review_path",
        hash_key="manual_screenshot_review_sha256",
        label="manual screenshot review",
        manifest=manifest,
        evidence_commit=evidence_commit,
        repo_root=root,
    )
    context = _read_json(context_path)
    output = Path(str(context.get("output_directory"))).resolve()
    if (
        output != context_path.parent
        or summary_path != output / "release-summary.json"
        or manual_path != output / "manual-screenshot-review.json"
        or manifest.get("attempt_context_path")
        != _repository_relative(root, context_path)
        or manifest.get("attempt_context_sha256")
        != seal.get("attempt_context_sha256")
        or manifest.get("readiness_path")
        != _repository_relative(root, readiness_path)
        or manifest.get("readiness_sha256")
        != seal.get("release_readiness_sha256")
    ):
        raise FinalReleaseGateError(
            "release seal context binding is invalid"
        )
    seal_hash = _file_sha256(path)
    for relative in _RELEASE_PLAN_PATHS:
        plan = root / relative
        evidence_plan = _committed_bytes(
            root,
            revision=evidence_commit,
            relative=relative,
        )
        final_plan = _committed_bytes(
            root,
            revision=commit,
            relative=relative,
        )
        if plan.read_bytes() != final_plan:
            raise FinalReleaseGateError(
                "release plan seal binding is invalid"
            )
        try:
            _validate_release_plan_closure(
                evidence_text=evidence_plan.decode("utf-8"),
                final_text=final_plan.decode("utf-8"),
                seal=seal,
                seal_relative=seal_relative,
                seal_sha256=seal_hash,
            )
        except UnicodeDecodeError as exc:
            raise FinalReleaseGateError(
                "release plan structure is invalid"
            ) from exc
    summary = _read_json(summary_path)
    manual = _read_json(manual_path)
    if (
        summary.get("schema_version")
        != "guide-final-release-summary-v1"
        or summary.get("passed") is not True
        or manual.get("schema_version")
        != "guide-manual-screenshot-review-v1"
        or manual.get("passed") is not True
        or manual.get("manual_screenshot_review_count") != 14
        or manual.get("manual_screenshot_failure_count") != 0
    ):
        raise FinalReleaseGateError(
            "release seal evidence is not passed"
        )
    _validate_sealed_release_evidence(
        context_path=context_path,
        readiness_path=readiness_path,
        summary_path=summary_path,
        manual_path=manual_path,
        repo_root=root,
    )
    readiness = _read_json(readiness_path)
    if (
        _file_sha256(readiness_path)
        != seal.get("release_readiness_sha256")
        or readiness.get("task11_commit")
        != task11_commit
        or readiness.get("plan_revision")
        != seal.get("plan_revision")
    ):
        raise FinalReleaseGateError(
            "release readiness seal binding is invalid"
        )
    execution_paths = readiness.get("release_execution_paths")
    execution_hashes = readiness.get(
        "release_execution_blob_sha256_by_path"
    )
    if (
        not isinstance(execution_paths, list)
        or not isinstance(execution_hashes, dict)
    ):
        raise FinalReleaseGateError(
            "release execution tree binding is invalid"
        )
    for relative in execution_paths:
        if relative in _RELEASE_PLAN_PATHS:
            continue
        current = root / str(relative)
        if (
            not current.is_file()
            or current.is_symlink()
            or _file_sha256(current) != execution_hashes.get(relative)
        ):
            raise FinalReleaseGateError(
                "release execution tree drift"
            )
    if subprocess.run(
        [
            "git",
            "status",
            "--porcelain=v1",
            "-z",
            "--untracked-files=all",
        ],
        cwd=root,
        check=True,
        capture_output=True,
    ).stdout:
        raise FinalReleaseGateError(
            "release seal requires a clean worktree"
        )
    return {"passed": True, **seal}


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    arguments = list(sys.argv[1:] if argv is None else argv)
    commands = {
        "build-evidence-manifest",
        "stage-evidence",
        "verify-evidence-staging",
        "create-seal",
        "verify-seal",
    }
    if arguments[:1] and arguments[0] in commands:
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(
            dest="command",
            required=True,
        )
        build = subparsers.add_parser("build-evidence-manifest")
        build.add_argument("--attempt-context", type=Path, required=True)
        build.add_argument("--readiness", type=Path, required=True)
        build.add_argument("--ledger", type=Path, required=True)
        build.add_argument(
            "--plan",
            dest="plans",
            action="append",
            type=Path,
            required=True,
        )
        build.add_argument("--output", type=Path, required=True)
        for name in ("stage-evidence", "verify-evidence-staging"):
            staging = subparsers.add_parser(name)
            staging.add_argument("--manifest", type=Path, required=True)
        create = subparsers.add_parser("create-seal")
        create.add_argument(
            "--attempt-context",
            type=Path,
            required=True,
        )
        create.add_argument("--evidence-commit", required=True)
        create.add_argument(
            "--manual-screenshot-review-from-context",
            action="store_true",
            required=True,
        )
        create.add_argument("--output", type=Path, required=True)
        verify = subparsers.add_parser("verify-seal")
        verify.add_argument("--seal", type=Path, required=True)
        verify.add_argument("--head", required=True)
        verify.add_argument(
            "--expected-evidence-commit",
            required=True,
        )
        return parser.parse_args(arguments)
    parser = argparse.ArgumentParser()
    parser.add_argument("--responsibility-matrix")
    parser.add_argument("--attempt-context", type=Path, required=True)
    parser.add_argument(
        "--phase",
        choices=("focused", "aggregate"),
        required=True,
    )
    return parser.parse_args(arguments)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    command = getattr(args, "command", None)
    if command == "build-evidence-manifest":
        result = build_evidence_manifest(
            attempt_context_path=args.attempt_context,
            readiness_path=args.readiness,
            ledger_path=args.ledger,
            plan_paths=args.plans,
            output_path=args.output,
        )
    elif command == "stage-evidence":
        stage_evidence(manifest_path=args.manifest)
        result = {"passed": True}
    elif command == "verify-evidence-staging":
        result = verify_evidence_staging(
            manifest_path=args.manifest,
        )
    elif command == "create-seal":
        result = create_release_seal(
            attempt_context_path=args.attempt_context,
            evidence_commit=args.evidence_commit,
            output_path=args.output,
        )
    elif command == "verify-seal":
        result = verify_release_seal(
            seal_path=args.seal,
            head=args.head,
            expected_evidence_commit=args.expected_evidence_commit,
        )
    elif args.phase == "focused":
        if not args.responsibility_matrix:
            raise SystemExit(
                "focused phase requires --responsibility-matrix"
            )
        result = run_focused_phase(
            responsibility_matrix=args.responsibility_matrix,
            attempt_context_path=args.attempt_context,
        )
    else:
        if args.responsibility_matrix:
            raise SystemExit(
                "aggregate phase forbids --responsibility-matrix"
            )
        result = run_aggregate_phase(
            attempt_context_path=args.attempt_context,
        )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "aggregate_release_gate",
    "build_evidence_manifest",
    "create_release_seal",
    "main",
    "run_aggregate_phase",
    "run_focused_gate",
    "run_focused_phase",
    "stage_evidence",
    "verify_evidence_staging",
    "verify_release_seal",
]
