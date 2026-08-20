"""Aggregate the focused and production-equivalent release gates."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
from typing import Mapping, Sequence

from tools.guide_gates.build_responsibility_matrix import (
    build_responsibility_matrix_rows,
)


_REPO_ROOT = Path(__file__).resolve().parents[2]
_GUIDE_RENDERER = _REPO_ROOT / "app/static/guide-presentation.js"
_CHAT_PAGE = _REPO_ROOT / "app/static/chat.html"


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
) -> dict[str, object]:
    summaries = (translation, backend, browser)
    wrong_binding_count = _sum(
        focused,
        *summaries,
        key="wrong_binding_count",
    )
    wrong_processor_count = _sum(
        focused,
        *summaries,
        key="wrong_processor_count",
    )
    wrong_presentation_count = _sum(
        focused,
        *summaries,
        key="wrong_presentation_count",
    )
    unsafe_downgrade_count = _sum(
        *summaries,
        key="unsafe_downgrade_count",
    )
    raw_ad_leak_count = _sum(*summaries, key="raw_ad_leak_count")
    internal_language_count = sum(
        max(
            _int(summary, "internal_language_count"),
            _int(summary, "internal_public_language_count"),
        )
        for summary in summaries
    )
    frontend_contract_violation_count = _sum(
        *summaries,
        key="frontend_contract_violation_count",
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
        "focused": dict(focused),
        "translation": dict(translation),
        "backend": dict(backend),
        "browser": dict(browser),
    }


def _translation_threshold(summary: Mapping[str, object]) -> bool:
    return (
        bool(summary.get("passed"))
        and _complete_critical_trajectories(summary)
        and _int(summary, "turn_count") >= 48
        and _int(summary, "passed_turn_count") >= 46
    )


def _backend_threshold(summary: Mapping[str, object]) -> bool:
    return (
        bool(summary.get("passed"))
        and _complete_critical_trajectories(summary)
        and _int(summary, "turn_count") >= 48
        and _int(summary, "completed_turn_count") >= 48
    )


def _browser_threshold(summary: Mapping[str, object]) -> bool:
    return (
        bool(summary.get("passed"))
        and _int(summary, "desktop_total") == 8
        and _int(summary, "desktop_passed") == 8
        and _int(summary, "mobile_total") == 8
        and _int(summary, "mobile_passed") == 8
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
    value = summary.get(key, 0)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{key} must be an integer")
    return value


def _sum(
    *summaries: Mapping[str, object],
    key: str,
) -> int:
    return sum(_int(summary, key) for summary in summaries)


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--responsibility-matrix")
    parser.add_argument("--focused")
    parser.add_argument("--translation")
    parser.add_argument("--backend")
    parser.add_argument("--browser")
    parser.add_argument("--output", required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    output = Path(args.output)
    if args.responsibility_matrix:
        result = run_focused_gate(Path(args.responsibility_matrix))
    elif all((args.focused, args.translation, args.backend, args.browser)):
        result = aggregate_release_gate(
            focused=_read_json(Path(args.focused)),
            translation=_read_json(Path(args.translation)),
            backend=_read_json(Path(args.backend)),
            browser=_read_json(Path(args.browser)),
        )
    else:
        raise SystemExit(
            "provide --responsibility-matrix or all final summary inputs"
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "aggregate_release_gate",
    "main",
    "run_focused_gate",
]
