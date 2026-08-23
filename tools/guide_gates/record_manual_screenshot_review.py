"""Record the hash-bound manual review of release browser screenshots."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from hashlib import sha256
import json
import os
from pathlib import Path
import re
from typing import Any

from tools.guide_gates.attempt_ledger import (
    AttemptLedgerError,
    read_attempt_context,
    read_ledger,
)
from tools.guide_gates.run_mainline_contract_browser_audit import (
    AuditBundleError,
    VIEWPORTS,
    validate_audit_bundle,
)


class ManualScreenshotReviewError(ValueError):
    """Raised when manual screenshot evidence is incomplete or invalid."""


_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCHEMA_VERSION = "guide-manual-screenshot-review-v1"
_BROWSER_SUMMARY_SCHEMA = "guide-mainline-contract-browser-audit-v1"
_VIEWPORTS = ("desktop", "mobile")
_MODES = (
    "explore_recommendation",
    "fit_recommendation",
    "product_knowledge",
    "comparison",
    "image_identity",
    "image_fit_recommendation",
    "image_comparison",
)
_ISSUE_CODES = frozenset({
    "overlap",
    "duplicate_answer_text",
    "repeated_card_surfaces",
    "missing_winner",
    "raw_internal_language",
    "wrong_price_specification_pair",
    "contract_field_mismatch",
})
_REVIEW_KEYS = frozenset({
    "viewport",
    "mode",
    "reviewer_id",
    "reviewed_at",
    "verdict",
    "issue_codes",
})
_ZERO_BROWSER_COUNTERS = (
    "serious_failure_count",
    "frontend_contract_violation_count",
    "wrong_binding_count",
    "unaligned_price_specification_count",
    "copywriter_fallback_count",
    "invalid_clarification_count",
)
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")


def _file_sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _duplicate_safe_object(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ManualScreenshotReviewError(
                f"duplicate JSON key: {key}"
            )
        result[key] = value
    return result


def _read_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_duplicate_safe_object,
        )
    except ManualScreenshotReviewError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ManualScreenshotReviewError(f"{label} is invalid") from exc
    if not isinstance(payload, dict):
        raise ManualScreenshotReviewError(f"{label} is invalid")
    return payload


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _repository_relative(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as exc:
        raise ManualScreenshotReviewError(
            "artifact path escapes repository"
        ) from exc


def _resolve_relative_path(
    *,
    base: Path,
    value: object,
    parent: Path,
    label: str,
) -> Path:
    if (
        not isinstance(value, str)
        or not value
        or Path(value).is_absolute()
    ):
        raise ManualScreenshotReviewError(f"{label} is invalid")
    path = (base / value).resolve()
    if not _is_within(path, parent.resolve()):
        raise ManualScreenshotReviewError(f"{label} escapes attempt")
    return path


def _browser_attempt(
    *,
    context_path: Path,
    context: Mapping[str, object],
    output_directory: Path,
) -> dict[str, Any]:
    phase_ids = context.get("phase_attempt_ids")
    if (
        not isinstance(phase_ids, dict)
        or set(phase_ids) != {"translation", "browser"}
        or not isinstance(phase_ids.get("browser"), str)
    ):
        raise ManualScreenshotReviewError(
            "attempt context phase binding is invalid"
        )
    try:
        ledger = read_ledger(Path(str(context["ledger_path"])))
    except (AttemptLedgerError, KeyError, OSError) as exc:
        raise ManualScreenshotReviewError(
            "attempt context ledger is invalid"
        ) from exc
    matches = [
        item
        for item in ledger["attempts"]
        if (
            isinstance(item, dict)
            and item.get("attempt_id") == phase_ids["browser"]
        )
    ]
    if len(matches) != 1:
        raise ManualScreenshotReviewError(
            "browser attempt binding is invalid"
        )
    attempt = matches[0]
    if attempt.get("result") != "passed":
        raise ManualScreenshotReviewError(
            "browser attempt has not passed"
        )
    if (
        attempt.get("trajectory_set") != "browser"
        or Path(str(attempt.get("context_path"))).resolve()
        != context_path.resolve()
        or Path(str(attempt.get("evidence_directory"))).resolve()
        != output_directory.resolve()
    ):
        raise ManualScreenshotReviewError(
            "browser attempt binding is invalid"
        )
    return attempt


def _load_context(
    attempt_context_path: Path,
    *,
    repo_root: Path,
) -> tuple[dict[str, Any], dict[str, Any], Path, Path]:
    context_path = attempt_context_path.resolve()
    if not _is_within(context_path, repo_root.resolve()):
        raise ManualScreenshotReviewError(
            "attempt context escapes repository"
        )
    raw_context = _read_object(
        context_path,
        label="attempt context",
    )
    try:
        ledger_path = Path(str(raw_context["ledger_path"]))
        readiness_path = Path(str(raw_context["readiness_path"]))
        context = read_attempt_context(
            context_path,
            ledger_path=ledger_path,
            readiness_path=readiness_path,
        )
    except (AttemptLedgerError, KeyError, OSError) as exc:
        raise ManualScreenshotReviewError(
            "attempt context is invalid"
        ) from exc
    output_directory = Path(
        str(context.get("output_directory"))
    ).resolve()
    if (
        output_directory != context_path.parent
        or not output_directory.is_dir()
        or not _is_within(output_directory, repo_root.resolve())
    ):
        raise ManualScreenshotReviewError(
            "attempt context output binding is invalid"
        )
    if (
        not readiness_path.is_file()
        or context.get("readiness_sha256")
        != _file_sha256(readiness_path)
    ):
        raise ManualScreenshotReviewError(
            "attempt context readiness hash mismatch"
        )
    readiness = _read_object(
        readiness_path,
        label="release readiness",
    )
    attempt = _browser_attempt(
        context_path=context_path,
        context=context,
        output_directory=output_directory,
    )
    if (
        readiness.get("plan_revision") != attempt.get("plan_revision")
        or readiness.get("candidate_head") != attempt.get("code_revision")
    ):
        raise ManualScreenshotReviewError(
            "attempt context release binding is invalid"
        )
    return context, attempt, output_directory, readiness_path


def _indexed_artifacts(
    *,
    summary: Mapping[str, object],
    repo_root: Path,
    output_directory: Path,
    summary_path: Path,
) -> dict[str, Path]:
    raw_index = summary.get("artifact_sha256")
    if not isinstance(raw_index, dict) or not raw_index:
        raise ManualScreenshotReviewError(
            "browser artifact index is invalid"
        )
    indexed: dict[str, Path] = {}
    allowed_roots = tuple(
        (output_directory / name).resolve()
        for name in (
            "browser-desktop",
            "browser-mobile",
            "mainline-browser",
        )
    )
    for raw_name, expected_hash in raw_index.items():
        if (
            not isinstance(raw_name, str)
            or not raw_name
            or Path(raw_name).is_absolute()
            or not isinstance(expected_hash, str)
            or _SHA256_PATTERN.fullmatch(expected_hash) is None
        ):
            raise ManualScreenshotReviewError(
                "browser artifact index is invalid"
            )
        path = (repo_root / raw_name).resolve()
        if (
            path == summary_path.resolve()
            or not any(_is_within(path, root) for root in allowed_roots)
            or not path.is_file()
            or path.is_symlink()
        ):
            raise ManualScreenshotReviewError(
                "browser artifact index is invalid"
            )
        normalized = _repository_relative(repo_root, path)
        if normalized != raw_name or normalized in indexed:
            raise ManualScreenshotReviewError(
                "browser artifact index is invalid"
            )
        if _file_sha256(path) != expected_hash:
            raise ManualScreenshotReviewError(
                f"artifact hash mismatch: {raw_name}"
            )
        indexed[normalized] = path

    actual = {
        _repository_relative(repo_root, path)
        for root in allowed_roots
        if root.is_dir()
        for path in root.rglob("*")
        if path.is_file() and path.resolve() != summary_path.resolve()
    }
    if set(indexed) != actual:
        raise ManualScreenshotReviewError(
            "browser artifact index does not match attempt files"
        )
    return indexed


def _contract_matches_mode(
    contract: Mapping[str, object],
    *,
    mode: str,
) -> bool:
    contract_mode = contract.get("mode")
    recommendation_mode = contract.get("recommendation_mode")
    expected = {
        "explore_recommendation": ("recommendation", "explore"),
        "fit_recommendation": ("recommendation", "fit"),
        "product_knowledge": ("product_knowledge", None),
        "comparison": ("comparison", None),
        "image_identity": ("image_identity", None),
        "image_fit_recommendation": ("recommendation", "fit"),
        "image_comparison": ("comparison", None),
    }[mode]
    return (contract_mode, recommendation_mode) == expected


def _validate_browser_summary(
    *,
    summary_path: Path,
    repo_root: Path,
    output_directory: Path,
) -> tuple[dict[tuple[str, str], dict[str, str]], str]:
    if not summary_path.is_file() or summary_path.is_symlink():
        raise ManualScreenshotReviewError(
            "release browser summary is missing"
        )
    summary = _read_object(
        summary_path,
        label="release browser summary",
    )
    if (
        summary.get("schema_version") != _BROWSER_SUMMARY_SCHEMA
        or summary.get("trajectory_set") != "release"
        or summary.get("viewport") != "all"
        or summary.get("passed") is not True
        or summary.get("turn_count") != 14
    ):
        raise ManualScreenshotReviewError(
            "release browser summary is invalid"
        )
    for key in _ZERO_BROWSER_COUNTERS:
        value = summary.get(key)
        if isinstance(value, bool) or value != 0:
            raise ManualScreenshotReviewError(
                "release browser summary is invalid"
            )
    indexed = _indexed_artifacts(
        summary=summary,
        repo_root=repo_root,
        output_directory=output_directory,
        summary_path=summary_path,
    )
    raw_turns = summary.get("turns")
    if not isinstance(raw_turns, list) or len(raw_turns) != 14:
        raise ManualScreenshotReviewError(
            "release browser summary requires exactly fourteen rows"
        )

    evidence: dict[tuple[str, str], dict[str, str]] = {}
    turn_directories: set[Path] = set()
    for raw in raw_turns:
        if not isinstance(raw, dict):
            raise ManualScreenshotReviewError(
                "release browser summary row is invalid"
            )
        viewport = raw.get("viewport")
        mode = raw.get("mode")
        turn_id = raw.get("turn_id")
        if viewport not in _VIEWPORTS:
            raise ManualScreenshotReviewError(
                "unknown review viewport"
            )
        if mode not in _MODES:
            raise ManualScreenshotReviewError(
                "unknown review mode"
            )
        if not isinstance(turn_id, str) or not turn_id:
            raise ManualScreenshotReviewError(
                "release browser turn ID is invalid"
            )
        key = (viewport, mode)
        if key in evidence:
            raise ManualScreenshotReviewError(
                "duplicate viewport/mode evidence row"
            )
        turn_dir = _resolve_relative_path(
            base=output_directory,
            value=raw.get("directory"),
            parent=output_directory / f"browser-{viewport}",
            label="browser turn directory",
        )
        if not turn_dir.is_dir() or turn_dir in turn_directories:
            raise ManualScreenshotReviewError(
                "browser turn directory is invalid"
            )
        screenshot = turn_dir / "screenshot.png"
        contract_path = turn_dir / "presentation-contract.json"
        request_path = turn_dir / "request.json"
        artifact_paths = (screenshot, contract_path, request_path)
        if any(
            _repository_relative(repo_root, path) not in indexed
            for path in artifact_paths
        ):
            raise ManualScreenshotReviewError(
                "review artifact is absent from browser index"
            )
        contract = _read_object(
            contract_path,
            label="presentation contract",
        )
        if not _contract_matches_mode(contract, mode=mode):
            raise ManualScreenshotReviewError(
                "presentation contract mode mismatch"
            )
        request = _read_object(request_path, label="browser request")
        if request.get("viewport") != VIEWPORTS[viewport]:
            raise ManualScreenshotReviewError(
                "browser request viewport mismatch"
            )
        try:
            validate_audit_bundle(
                turn_dir,
                expected_turn_id=turn_id,
            )
        except (AuditBundleError, OSError, UnicodeError) as exc:
            raise ManualScreenshotReviewError(
                f"browser audit bundle is invalid: {turn_id}"
            ) from exc
        evidence[key] = {
            "turn_id": turn_id,
            "artifact_directory": _repository_relative(
                repo_root,
                turn_dir,
            ),
            "screenshot_path": _repository_relative(
                repo_root,
                screenshot,
            ),
            "screenshot_sha256": _file_sha256(screenshot),
            "presentation_contract_path": _repository_relative(
                repo_root,
                contract_path,
            ),
            "presentation_contract_sha256": _file_sha256(
                contract_path
            ),
        }
        turn_directories.add(turn_dir)

    expected = {
        (viewport, mode)
        for viewport in _VIEWPORTS
        for mode in _MODES
    }
    if set(evidence) != expected:
        raise ManualScreenshotReviewError(
            "release evidence does not contain exactly fourteen "
            "viewport/mode rows"
        )
    indexed_screenshot_directories = {
        path.parent
        for name, path in indexed.items()
        if name.endswith("/screenshot.png")
    }
    indexed_contract_directories = {
        path.parent
        for name, path in indexed.items()
        if name.endswith("/presentation-contract.json")
    }
    if (
        indexed_screenshot_directories != turn_directories
        or indexed_contract_directories != turn_directories
    ):
        raise ManualScreenshotReviewError(
            "release evidence contains unknown or missing turn artifacts"
        )
    return evidence, _file_sha256(summary_path)


def _parse_reviewed_at(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise ManualScreenshotReviewError("reviewed_at is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ManualScreenshotReviewError(
            "reviewed_at is invalid"
        ) from exc
    if parsed.utcoffset() is None:
        raise ManualScreenshotReviewError(
            "reviewed_at must be timezone-aware"
        )
    return value


def _validated_reviews(
    reviews: Sequence[Mapping[str, object]],
) -> dict[tuple[str, str], dict[str, object]]:
    if isinstance(reviews, (str, bytes)) or len(reviews) != 14:
        raise ManualScreenshotReviewError(
            "manual screenshot review requires exactly fourteen rows"
        )
    normalized: dict[tuple[str, str], dict[str, object]] = {}
    for raw in reviews:
        if not isinstance(raw, Mapping) or set(raw) != _REVIEW_KEYS:
            raise ManualScreenshotReviewError(
                "manual screenshot review row is invalid"
            )
        viewport = raw["viewport"]
        mode = raw["mode"]
        if viewport not in _VIEWPORTS:
            raise ManualScreenshotReviewError(
                "unknown review viewport"
            )
        if mode not in _MODES:
            raise ManualScreenshotReviewError(
                "unknown review mode"
            )
        key = (viewport, mode)
        if key in normalized:
            raise ManualScreenshotReviewError(
                "duplicate viewport/mode review row"
            )
        reviewer_id = raw["reviewer_id"]
        if (
            not isinstance(reviewer_id, str)
            or not reviewer_id.strip()
            or reviewer_id != reviewer_id.strip()
        ):
            raise ManualScreenshotReviewError(
                "reviewer ID is invalid"
            )
        verdict = raw["verdict"]
        if verdict not in {"passed", "failed"}:
            raise ManualScreenshotReviewError(
                "review verdict is invalid"
            )
        issue_codes = raw["issue_codes"]
        if (
            not isinstance(issue_codes, (list, tuple))
            or any(not isinstance(item, str) for item in issue_codes)
            or len(issue_codes) != len(set(issue_codes))
        ):
            raise ManualScreenshotReviewError(
                "review issue codes are invalid"
            )
        unknown = set(issue_codes) - _ISSUE_CODES
        if unknown:
            raise ManualScreenshotReviewError(
                "unknown issue code: " + ", ".join(sorted(unknown))
            )
        if (verdict == "passed") != (len(issue_codes) == 0):
            raise ManualScreenshotReviewError(
                "review verdict and issue codes disagree"
            )
        normalized[key] = {
            "viewport": viewport,
            "mode": mode,
            "reviewer_id": reviewer_id,
            "reviewed_at": _parse_reviewed_at(raw["reviewed_at"]),
            "verdict": verdict,
            "issue_codes": list(issue_codes),
        }
    expected = {
        (viewport, mode)
        for viewport in _VIEWPORTS
        for mode in _MODES
    }
    if set(normalized) != expected:
        raise ManualScreenshotReviewError(
            "manual screenshot review is missing viewport/mode rows"
        )
    return normalized


def _write_exclusive_json(path: Path, payload: object) -> None:
    data = (
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")
    try:
        with path.open("xb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
    except FileExistsError as exc:
        raise ManualScreenshotReviewError(
            "manual screenshot review already exists"
        ) from exc
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def record_manual_screenshot_review(
    *,
    attempt_context_path: str | Path,
    reviews: Sequence[Mapping[str, object]],
    repo_root: str | Path = _REPO_ROOT,
) -> dict[str, object]:
    """Validate and record one immutable fourteen-row manual review."""
    root = Path(repo_root).resolve()
    context_path = Path(attempt_context_path)
    output_path = context_path.resolve().parent / (
        "manual-screenshot-review.json"
    )
    if output_path.exists() or output_path.is_symlink():
        raise ManualScreenshotReviewError(
            "manual screenshot review already exists"
        )
    context, attempt, output_directory, readiness_path = _load_context(
        context_path,
        repo_root=root,
    )
    summary_path = output_directory / "mainline-browser/summary.json"
    evidence, summary_sha256 = _validate_browser_summary(
        summary_path=summary_path,
        repo_root=root,
        output_directory=output_directory,
    )
    review_by_key = _validated_reviews(reviews)
    rows: list[dict[str, object]] = []
    for viewport in _VIEWPORTS:
        for mode in _MODES:
            key = (viewport, mode)
            rows.append({
                **evidence[key],
                **review_by_key[key],
            })
    failure_count = sum(
        row["verdict"] == "failed" for row in rows
    )
    result: dict[str, object] = {
        "schema_version": _SCHEMA_VERSION,
        "passed": failure_count == 0,
        "plan_revision": attempt["plan_revision"],
        "code_revision": attempt["code_revision"],
        "attempt_id": attempt["attempt_id"],
        "attempt_context_path": _repository_relative(
            root,
            context_path,
        ),
        "attempt_context_sha256": _file_sha256(context_path),
        "readiness_path": _repository_relative(
            root,
            readiness_path,
        ),
        "readiness_sha256": context["readiness_sha256"],
        "browser_summary_path": _repository_relative(
            root,
            summary_path,
        ),
        "browser_summary_sha256": summary_sha256,
        "controlled_issue_codes": sorted(_ISSUE_CODES),
        "manual_screenshot_review_count": len(rows),
        "manual_screenshot_failure_count": failure_count,
        "rows": rows,
    }
    _write_exclusive_json(output_path, result)
    return result


def _interactive_reviews(
    evidence: Mapping[tuple[str, str], Mapping[str, str]],
    *,
    input_fn: Callable[[str], str],
) -> list[dict[str, object]]:
    reviewer_id = input_fn("Reviewer ID: ").strip()
    reviews: list[dict[str, object]] = []
    for viewport in _VIEWPORTS:
        for mode in _MODES:
            target = evidence[(viewport, mode)]
            print(
                f"[{viewport} / {mode}]\n"
                f"  screenshot: {target['screenshot_path']}\n"
                "  contract: "
                f"{target['presentation_contract_path']}"
            )
            verdict = input_fn("Verdict [passed/failed]: ").strip()
            issue_codes: list[str] = []
            if verdict == "failed":
                raw_codes = input_fn(
                    "Issue codes (comma-separated): "
                )
                issue_codes = [
                    item.strip()
                    for item in raw_codes.split(",")
                    if item.strip()
                ]
            reviews.append({
                "viewport": viewport,
                "mode": mode,
                "reviewer_id": reviewer_id,
                "reviewed_at": (
                    datetime.now(UTC)
                    .isoformat()
                    .replace("+00:00", "Z")
                ),
                "verdict": verdict,
                "issue_codes": issue_codes,
            })
    return reviews


def _parse_args(
    argv: Sequence[str] | None = None,
) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--attempt-context",
        type=Path,
        required=True,
    )
    return parser.parse_args(argv)


def main(
    argv: Sequence[str] | None = None,
    *,
    input_fn: Callable[[str], str] = input,
) -> int:
    args = _parse_args(argv)
    root = _REPO_ROOT.resolve()
    context, _, output_directory, _ = _load_context(
        args.attempt_context,
        repo_root=root,
    )
    evidence, _ = _validate_browser_summary(
        summary_path=(
            output_directory / "mainline-browser/summary.json"
        ),
        repo_root=root,
        output_directory=output_directory,
    )
    reviews = _interactive_reviews(evidence, input_fn=input_fn)
    result = record_manual_screenshot_review(
        attempt_context_path=args.attempt_context,
        reviews=reviews,
        repo_root=root,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "ManualScreenshotReviewError",
    "main",
    "record_manual_screenshot_review",
]
