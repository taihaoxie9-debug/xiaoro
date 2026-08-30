from pathlib import Path
import shutil

import pytest

from tools.guide_gates import run_task11_independent_audit as audit


ROOT = Path(__file__).resolve().parents[3]
REPAIR_ROOT = (
    ROOT
    / "docs/audits/final-release/mainline-contract-closure/"
    "repair-epoch-26"
)
RUNTIME_REPAIR_ROOT = (
    ROOT
    / "docs/audits/final-release/mainline-contract-closure/"
    "repair-epoch-62"
)


def test_historical_patch_accepts_reverse_applicable_descendant(
    tmp_path: Path,
) -> None:
    candidate = tmp_path / "candidate"
    for relative in audit.RECLASSIFICATION_PATCH_PATHS:
        source = ROOT / relative
        target = candidate / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    chat = candidate / "app/static/chat.html"
    chat.write_text(
        chat.read_text(encoding="utf-8").replace(
            (
                "            if (!isActiveChatRequest(requestContext)) "
                "return;\n"
                "            if (\n"
            ),
            (
                "            if (!isActiveChatRequest(requestContext)) "
                "return;\n"
                "            setConversationVersion(\n"
                "                sessionId,\n"
                "                deferredConversationVersion\n"
                "            );\n"
                "            if (\n"
            ),
            1,
        ),
        encoding="utf-8",
    )
    patch = REPAIR_ROOT / "attempt-08-frontend-delivery-repair.patch"

    exact_postimages = audit._validate_reverse_applicable_historical_patch(
        root=candidate,
        patch_path=patch,
        patch_blobs={
            "app/static/chat.html": ("0" * 7, "1" * 7),
            "tests/guide/runtime/test_feedback_frontend.py": (
                "2" * 7,
                "3" * 7,
            ),
        },
        label="repair patch",
    )

    assert exact_postimages == frozenset()


def test_historical_patch_rejects_candidate_without_repair(
    tmp_path: Path,
) -> None:
    candidate = tmp_path / "candidate"
    patch = REPAIR_ROOT / "attempt-08-frontend-delivery-repair.patch"
    for relative in audit.RECLASSIFICATION_PATCH_PATHS:
        source = ROOT / relative
        target = candidate / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    chat = candidate / "app/static/chat.html"
    chat.write_text(
        chat.read_text(encoding="utf-8").replace(
            "&& inlineProducts.length > 0",
            "",
            1,
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        audit.Task11IndependentAuditError,
        match="does not reverse-apply",
    ):
        audit._validate_reverse_applicable_historical_patch(
            root=candidate,
            patch_path=patch,
            patch_blobs={},
            label="repair patch",
        )


def test_historical_patch_rejects_relocated_change_without_hunk_context(
    tmp_path: Path,
) -> None:
    candidate = tmp_path / "candidate"
    patch = REPAIR_ROOT / "attempt-08-frontend-delivery-repair.patch"
    for relative in audit.RECLASSIFICATION_PATCH_PATHS:
        source = ROOT / relative
        target = candidate / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    chat = candidate / "app/static/chat.html"
    chat.write_text(
        chat.read_text(encoding="utf-8").replace(
            "// owner check: before version write",
            "// unrelated owner check",
            1,
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        audit.Task11IndependentAuditError,
        match="does not reverse-apply",
    ):
        audit._validate_reverse_applicable_historical_patch(
            root=candidate,
            patch_path=patch,
            patch_blobs={
                "app/static/chat.html": ("0" * 7, "1" * 7),
                "tests/guide/runtime/test_feedback_frontend.py": (
                    "2" * 7,
                    "3" * 7,
                ),
            },
            label="repair patch",
        )


def test_runtime_gate_repair_accepts_current_descendant_candidate() -> None:
    repair_files = {
        "pre_fix_reproduction": (
            RUNTIME_REPAIR_ROOT
            / "attempt-10-pre-fix-reproduction.xml"
        ),
        "post_fix_verification": (
            RUNTIME_REPAIR_ROOT
            / "attempt-10-post-fix-verification.xml"
        ),
        "focused_zero_api": (
            RUNTIME_REPAIR_ROOT
            / "attempt-10-focused-zero-api.xml"
        ),
        "repair_patch": (
            RUNTIME_REPAIR_ROOT
            / "attempt-10-runtime-gate-repair.patch"
        ),
    }

    report = audit.validate_runtime_shell_lease_repair_evidence(
        repair_files=repair_files,
        repo_root=ROOT,
    )

    assert report["regression_node_count"] == 2
    assert report["historical_focused_test_count"] == 491
    assert report["current_focused_test_count"] > 491
    assert report["historical_red_evidence_preserved"] is True
    assert report["live_preimage_outcome"] == "superseded_descendant"
    assert report["live_red_exit_code"] is None
    assert report["live_green_exit_code"] == 0
