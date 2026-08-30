from pathlib import Path

import pytest

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
    def dom(
        *,
        mode: str,
        product_count: int,
        inline_count: int,
        comparison_count: int = 0,
        winner_count: int = 0,
    ) -> dict[str, object]:
        return {
            "horizontal_overflow": False,
            "unloaded_images": [],
            "presentation_count": 1,
            "last_mode": mode,
            "legacy_full_card_count": 0,
            "shelf_reason_count": 0,
            "fit_pending_count": 0,
            "shelf_card_count": product_count,
            "inline_card_count": inline_count,
            "comparison_table_count": comparison_count,
            "winner_count": winner_count,
        }

    first_batch = [38, 91]
    first = browser_audit._assert_turn(
        trajectory_id="consultation_return_comparison",
        turn_index=1,
        expected_modes={"recommendation"},
        event={
            "event_names": ["end"],
            "message_count": 0,
            "presentation_count": 1,
            "clarify_count": 0,
            "presentation": {
                "mode": "recommendation",
                "copy_source": "model",
            },
            "product_ids": first_batch,
            "clarification": False,
        },
        dom=dom(
            mode="recommendation",
            product_count=2,
            inline_count=2,
        ),
        prior_products=None,
    )
    second = browser_audit._assert_turn(
        trajectory_id="consultation_return_comparison",
        turn_index=2,
        expected_modes={"consultation"},
        event={
            "event_names": ["end"],
            "message_count": 0,
            "presentation_count": 1,
            "clarify_count": 0,
            "presentation": {
                "mode": "consultation",
                "copy_source": "model",
            },
            "product_ids": [],
            "clarification": False,
        },
        dom=dom(
            mode="consultation",
            product_count=0,
            inline_count=0,
        ),
        prior_products=first,
    )
    third = browser_audit._assert_turn(
        trajectory_id="consultation_return_comparison",
        turn_index=3,
        expected_modes={"comparison"},
        event={
            "event_names": ["end"],
            "message_count": 0,
            "presentation_count": 1,
            "clarify_count": 0,
            "presentation": {
                "mode": "comparison",
                "copy_source": "model",
            },
            "product_ids": first_batch,
            "clarification": False,
        },
        dom=dom(
            mode="comparison",
            product_count=2,
            inline_count=0,
            comparison_count=1,
            winner_count=1,
        ),
        prior_products=second,
    )

    assert first == first_batch
    assert second == first_batch
    assert third == first_batch


def test_browser_audit_rejects_legacy_message_event() -> None:
    event = {
        "event_names": [
            "start",
            "intent",
            "presentation_contract",
            "message",
            "end",
        ],
        "message": "legacy body",
        "message_count": 1,
        "presentation_count": 1,
        "clarify_count": 0,
        "presentation": {
            "mode": "recommendation",
            "copy_source": "model",
        },
        "product_ids": [38],
        "clarification": False,
    }
    dom = {
        "horizontal_overflow": False,
        "unloaded_images": [],
        "presentation_count": 1,
        "last_mode": "recommendation",
        "legacy_full_card_count": 0,
        "shelf_reason_count": 0,
        "fit_pending_count": 0,
        "shelf_card_count": 1,
        "inline_card_count": 1,
        "comparison_table_count": 0,
        "winner_count": 0,
    }

    with pytest.raises(AssertionError):
        browser_audit._assert_turn(
            trajectory_id="product_focus",
            turn_index=1,
            expected_modes={"recommendation"},
            event=event,
            dom=dom,
            prior_products=None,
        )


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


def test_browser_audit_collects_current_contract_renderer_metrics() -> None:
    class PageProbe:
        def __init__(self) -> None:
            self.script = ""

        def evaluate(self, script: str) -> dict[str, object]:
            self.script = script
            return {}

    page = PageProbe()

    assert browser_audit._dom_evidence(page) == {}
    assert ".guide-presentation-root" in page.script
    assert "[data-section-kind]" in page.script
    assert '[data-guide-card-form="shelf"]' in page.script
    assert '[data-guide-card-form="full"]' in page.script
    assert "shelf_reason_count" in page.script
