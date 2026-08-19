from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import random

import pytest

from tools.guide_gates.continuous_conversation_blind_fixture import (
    BLIND_SHUFFLE_SEED,
    freeze_blind_exams,
    load_blind_exams,
    normalized_messages,
)
from tools.guide_gates.continuous_conversation_fixture import (
    load_frozen_trajectories,
    load_trajectory_pool,
    no_simple_paraphrase_pairs,
)
from tools.guide_gates.continuous_conversation_gate import (
    ContinuousTrajectory,
)


FIXTURE_DIRECTORY = Path("tests/fixtures/guide/conversation")
BLIND_POOL_PATH = FIXTURE_DIRECTORY / "continuous_blind_pool_v1.jsonl"
FIXED_PATH = FIXTURE_DIRECTORY / "continuous_20x5_v1.jsonl"
FIXED_MANIFEST_PATH = (
    FIXTURE_DIRECTORY / "continuous_20x5_v1_manifest.json"
)
REQUIRED_ROUTE_FAMILIES = {
    "recommendation_revision",
    "product_followup",
    "general_knowledge_return",
    "comparison",
    "consultation_profile",
    "image_identity",
    "image_suitability",
    "image_similarity",
    "clarification_recovery",
    "safety_escalation",
    "pending_turn",
}


def _blind_paths(directory: Path) -> tuple[Path, Path, Path, Path]:
    return (
        directory / "continuous_blind_a_20x5_v1.jsonl",
        directory / "continuous_blind_a_20x5_v1_manifest.json",
        directory / "continuous_blind_b_20x5_v1.jsonl",
        directory / "continuous_blind_b_20x5_v1_manifest.json",
    )


def _freeze_into(directory: Path) -> tuple[Path, Path, Path, Path]:
    a_path, a_manifest_path, b_path, b_manifest_path = _blind_paths(
        directory
    )
    freeze_blind_exams(
        pool_path=BLIND_POOL_PATH,
        blind_a_path=a_path,
        blind_a_manifest_path=a_manifest_path,
        blind_b_path=b_path,
        blind_b_manifest_path=b_manifest_path,
    )
    return a_path, a_manifest_path, b_path, b_manifest_path


def _load_from(
    paths: tuple[Path, Path, Path, Path],
) -> tuple[
    tuple[ContinuousTrajectory, ...],
    tuple[ContinuousTrajectory, ...],
]:
    a_path, a_manifest_path, b_path, b_manifest_path = paths
    return load_blind_exams(
        blind_a_path=a_path,
        blind_a_manifest_path=a_manifest_path,
        blind_b_path=b_path,
        blind_b_manifest_path=b_manifest_path,
    )


def test_blind_pool_has_forty_independent_five_turn_trajectories(
) -> None:
    pool = load_trajectory_pool(BLIND_POOL_PATH)
    original_pool = load_trajectory_pool(
        FIXTURE_DIRECTORY / "continuous_trajectory_pool_v1.jsonl"
    )

    assert len(pool) == 40
    assert all(len(item.turns) == 5 for item in pool)
    assert len({item.trajectory_id for item in pool}) == 40
    assert len(normalized_messages(pool)) == 200
    assert no_simple_paraphrase_pairs(pool)
    assert all(item.subject_scope == "self" for item in pool)
    assert all(
        "other" not in turn.acceptable_semantic.subject_scope_hints
        for item in pool
        for turn in item.turns
    )
    assert normalized_messages(pool).isdisjoint(
        normalized_messages(original_pool)
    )


def test_blind_exams_are_disjoint_from_fixed_and_each_other() -> None:
    fixed = load_frozen_trajectories(
        FIXED_PATH,
        manifest_path=FIXED_MANIFEST_PATH,
    )
    blind_a, blind_b = load_blind_exams()

    fixed_ids = {item.trajectory_id for item in fixed}
    a_ids = {item.trajectory_id for item in blind_a}
    b_ids = {item.trajectory_id for item in blind_b}

    assert len(blind_a) == len(blind_b) == 20
    assert all(len(item.turns) == 5 for item in (*blind_a, *blind_b))
    assert all(
        item.subject_scope == "self"
        for item in (*blind_a, *blind_b)
    )
    assert fixed_ids.isdisjoint(a_ids)
    assert fixed_ids.isdisjoint(b_ids)
    assert a_ids.isdisjoint(b_ids)
    assert normalized_messages(fixed).isdisjoint(
        normalized_messages(blind_a)
    )
    assert normalized_messages(fixed).isdisjoint(
        normalized_messages(blind_b)
    )
    assert normalized_messages(blind_a).isdisjoint(
        normalized_messages(blind_b)
    )


def test_each_blind_exam_covers_all_stateful_route_families() -> None:
    blind_a, blind_b = load_blind_exams()

    for exam in (blind_a, blind_b):
        families = {
            family
            for trajectory in exam
            for family in trajectory.route_families
        }
        assert REQUIRED_ROUTE_FAMILIES <= families


def test_each_blind_exam_has_five_trajectories_per_route_group() -> None:
    blind_a, blind_b = load_blind_exams()

    for exam in (blind_a, blind_b):
        groups = Counter(
            trajectory.trajectory_id.split("-")[1]
            for trajectory in exam
        )
        assert groups == {
            "rpf": 5,
            "kcr": 5,
            "cps": 5,
            "img": 5,
        }


def test_image_identity_and_similarity_expectations_follow_new_contract(
) -> None:
    pool = load_trajectory_pool(BLIND_POOL_PATH)

    for trajectory in pool:
        if not trajectory.trajectory_id.startswith("blind-img-"):
            continue
        identity = trajectory.turns[0]
        image_bindings = identity.expected_bindings
        expected_refs = [
            {
                "image_ordinal": ordinal,
                "product_id": binding.product_id,
                "variant_scope": binding.variant_scope,
            }
            for ordinal, binding in enumerate(
                image_bindings,
                start=1,
            )
        ]
        focus = identity.expected_snapshot_subset["focus_state"]

        assert identity.expected_route.processor == "image_identity"
        assert identity.expected_presentation_mode == "image_identity"
        assert (
            identity.expected_snapshot_subset["has_image_delivery"]
            is True
        )
        assert focus["active_processor"] == "image_identity"
        assert focus["confirmed_image_products"] == expected_refs
        assert focus["current_product_id"] == (
            image_bindings[0].product_id
            if len(image_bindings) == 1
            else None
        )

        anchor_product_id = (
            53
            if trajectory.trajectory_id
            == "blind-img-07-ambiguous-return"
            else image_bindings[0].product_id
        )
        for turn in trajectory.turns:
            if (
                    turn.expected_route.processor != "recommendation"
                    or
                "image_similarity"
                not in turn.acceptable_semantic.operation_hints
            ):
                continue
            assert anchor_product_id not in turn.expected_card_ids


def test_pending_turn_family_contains_clarification_then_resume() -> None:
    pool = load_trajectory_pool(BLIND_POOL_PATH)
    pending = [
        trajectory
        for trajectory in pool
        if "pending_turn" in trajectory.route_families
    ]

    assert len(pending) == 2
    for trajectory in pending:
        first, second = trajectory.turns[:2]
        assert first.expected_route.processor == "clarification"
        assert first.expected_clarification is True
        assert first.expected_card_ids == ()
        assert first.expected_snapshot_subset["pending_turn"] == {
            "gap": "budget",
            "resume_mode": "recommendation",
            "resume_context": {"category": "serum"},
        }
        assert (
            "clarification"
            in second.acceptable_semantic.operation_hints
        )
        assert None in second.acceptable_semantic.topic_hints
        assert "skincare" in second.acceptable_semantic.topic_hints
        assert second.expected_route.processor == "recommendation"
        assert second.expected_route.continuity == "correct"
        assert second.expected_clarification is False
        assert second.expected_card_ids


def test_blind_general_knowledge_switch_uses_code_owned_continuity(
) -> None:
    turns = [
        turn
        for trajectory in load_trajectory_pool(BLIND_POOL_PATH)
        for index, turn in enumerate(trajectory.turns)
        if (
            index > 0
            and turn.expected_route.processor == "general_knowledge"
            and turn.expected_route.continuity == "replace_task"
            and not turn.expected_bindings
        )
    ]

    assert len(turns) == 17
    assert all(
        "continue" in turn.acceptable_semantic.continuity_hints
        for turn in turns
    )


def test_blind_named_comparison_switch_uses_code_owned_continuity(
) -> None:
    turns = [
        turn
        for trajectory in load_trajectory_pool(BLIND_POOL_PATH)
        for turn in trajectory.turns
        if (
            turn.expected_route.processor == "comparison"
            and turn.expected_route.continuity == "replace_task"
            and turn.expected_route.focus_source == "explicit_product"
        )
    ]

    assert len(turns) == 11
    assert all(
        "continue" in turn.acceptable_semantic.continuity_hints
        for turn in turns
    )


def test_blind_product_return_uses_code_owned_continuity() -> None:
    turns = [
        current
        for trajectory in load_trajectory_pool(BLIND_POOL_PATH)
        for previous, current in zip(
            trajectory.turns,
            trajectory.turns[1:],
        )
        if (
            previous.expected_route.processor == "general_knowledge"
            and current.expected_route.processor == "product_knowledge"
            and current.expected_route.continuity == "return_to_focus"
        )
    ]

    assert len(turns) == 11
    assert all(
        "continue" in turn.acceptable_semantic.continuity_hints
        for turn in turns
    )


def test_load_blind_exams_rejects_manifest_hash_drift(
    tmp_path: Path,
) -> None:
    paths = _freeze_into(tmp_path)
    a_path = paths[0]
    lines = a_path.read_text(encoding="utf-8").splitlines()
    drifted = json.loads(lines[0])
    drifted["turns"][0]["message"] += "（漂移）"
    lines[0] = ContinuousTrajectory.model_validate(
        drifted,
        strict=True,
    ).model_dump_json()
    a_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="manifest hash mismatch"):
        _load_from(paths)


def test_freeze_blind_exams_is_seeded_deterministic_and_disjoint(
    tmp_path: Path,
) -> None:
    pool = load_trajectory_pool(BLIND_POOL_PATH)
    randomizer = random.Random(2026081801)
    expected_a = []
    expected_b = []
    for group_name in ("rpf", "kcr", "cps", "img"):
        group = [
            item
            for item in pool
            if item.trajectory_id.split("-")[1] == group_name
        ]
        randomizer.shuffle(group)
        expected_a.extend(group[:5])
        expected_b.extend(group[5:])
    expected_a_ids = tuple(sorted(
        item.trajectory_id for item in expected_a
    ))
    expected_b_ids = tuple(sorted(
        item.trajectory_id for item in expected_b
    ))
    first_paths = _freeze_into(tmp_path / "first")
    second_paths = _freeze_into(tmp_path / "second")
    first_a, first_b = _load_from(first_paths)
    second_a, second_b = _load_from(second_paths)

    assert BLIND_SHUFFLE_SEED == 2026081801
    assert first_a == second_a
    assert first_b == second_b
    assert tuple(item.trajectory_id for item in first_a) == expected_a_ids
    assert tuple(item.trajectory_id for item in first_b) == expected_b_ids
    assert first_paths[0].read_bytes() == second_paths[0].read_bytes()
    assert first_paths[2].read_bytes() == second_paths[2].read_bytes()
    assert {
        item.trajectory_id for item in first_a
    }.isdisjoint({
        item.trajectory_id for item in first_b
    })
