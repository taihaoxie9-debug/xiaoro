from pathlib import Path

from tools.guide_gates import (
    run_real_continuous_conversation_browser_audit as browser_audit,
)


ROOT = Path(__file__).resolve().parents[3]


def _real_image_trajectory() -> dict[str, object]:
    return next(
        trajectory
        for trajectory in browser_audit.TRAJECTORIES
        if trajectory["id"] == "real_images"
    )


def _consultation_return_comparison_trajectory() -> dict[str, object]:
    return next(
        trajectory
        for trajectory in browser_audit.TRAJECTORIES
        if trajectory["id"] == "consultation_return_comparison"
    )


def test_browser_audit_includes_consultation_return_comparison_path() -> None:
    trajectory = _consultation_return_comparison_trajectory()

    assert trajectory["turns"] == (
        "油敏肌，夏天通勤想找修护精华，预算300内，先推荐两款。",
        (
            "先不继续选产品。我下午鼻子出油，洗脸后两颊发紧，"
            "帮我判断我现在的肤质和状态。"
        ),
        "现在再回到刚才的两款精华，按我这个状态，哪款更适合？",
    )
    assert trajectory["modes"] == (
        {"recommendation"},
        {"consultation"},
        {"comparison"},
    )


def test_consultation_return_comparison_keeps_initial_batch_for_comparison(
) -> None:
    dom = {
        "horizontal_overflow": False,
        "unloaded_images": [],
    }
    first_batch = [38, 91]
    first = browser_audit._assert_turn(
        trajectory_id="consultation_return_comparison",
        turn_index=1,
        expected_modes={"recommendation"},
        event={
            "event_names": ["end"],
            "message": "推荐结果",
            "presentation": {
                "mode": "recommendation",
                "copy_source": "model",
            },
            "product_ids": first_batch,
            "clarification": False,
        },
        dom=dom,
        prior_products=None,
    )
    second = browser_audit._assert_turn(
        trajectory_id="consultation_return_comparison",
        turn_index=2,
        expected_modes={"consultation"},
        event={
            "event_names": ["end"],
            "message": "问诊结果",
            "presentation": {
                "mode": "consultation",
                "copy_source": "model",
            },
            "product_ids": [],
            "clarification": False,
        },
        dom=dom,
        prior_products=first,
    )
    third = browser_audit._assert_turn(
        trajectory_id="consultation_return_comparison",
        turn_index=3,
        expected_modes={"comparison"},
        event={
            "event_names": ["end"],
            "message": "比较结果",
            "presentation": {
                "mode": "comparison",
                "copy_source": "model",
            },
            "product_ids": first_batch,
            "clarification": False,
        },
        dom=dom,
        prior_products=second,
    )

    assert first == first_batch
    assert second == first_batch
    assert third == first_batch


def test_real_image_browser_path_accepts_grounded_clarification_then_recovers(
) -> None:
    trajectory = _real_image_trajectory()

    assert trajectory["modes"] == (
        {None},
        {"image_identity"},
        {"product_knowledge", "single_product"},
        {"recommendation", "image_recommendation"},
        {"product_knowledge", "single_product", "followup"},
    )
    assert len(trajectory["recovery_images"]) == 2


def test_recovery_uploads_are_reencoded_and_not_index_hashes() -> None:
    trajectory = _real_image_trajectory()

    uploads = browser_audit._image_uploads_for_turn(
        trajectory=trajectory,
        turn_index=2,
        root=ROOT,
    )

    assert len(uploads) == 2
    assert all(isinstance(upload, dict) for upload in uploads)
    assert all(upload["mimeType"] == "image/png" for upload in uploads)
    assert all(upload["name"].endswith(".png") for upload in uploads)
    assert all(upload["buffer"].startswith(b"\x89PNG\r\n\x1a\n") for upload in uploads)
    assert all(
        upload["buffer"] != (ROOT / source).read_bytes()
        for upload, source in zip(
            uploads,
            trajectory["recovery_images"],
            strict=True,
        )
    )


def test_browser_evidence_waits_for_pending_images_before_dom_assertions(
) -> None:
    calls: list[tuple[str, int]] = []

    class PageProbe:
        def wait_for_function(
            self,
            expression: str,
            *,
            timeout: int,
        ) -> None:
            calls.append((expression, timeout))

    browser_audit._wait_for_loaded_images(PageProbe())

    assert calls == [
        (
            "() => Array.from(document.images).every("
            "image => !image.src || image.complete"
            ")",
            5000,
        )
    ]
