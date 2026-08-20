from __future__ import annotations

from collections import Counter
from pathlib import Path

from app.guide.adapters.catalog import CanonicalProductReader
from app.guide_runtime.composition import build_selection_concept_assets
from tools.guide_gates.continuous_conversation_fixture import (
    BACKEND_SELECTION_SEED,
    build_continuous_fixture_manifest,
    load_frozen_trajectories,
    load_trajectory_pool,
    no_simple_paraphrase_pairs,
    normalize_message,
    select_backend_trajectories,
)


POOL_PATH = Path(
    "tests/fixtures/guide/conversation/"
    "continuous_trajectory_pool_v1.jsonl"
)
FROZEN_PATH = Path(
    "tests/fixtures/guide/conversation/"
    "continuous_20x5_v1.jsonl"
)
MANIFEST_PATH = Path(
    "tests/fixtures/guide/conversation/"
    "continuous_20x5_v1_manifest.json"
)
CANONICAL_MANIFEST_PATH = Path(
    "data/canonical/core_products_v1_manifest.json"
)
CANONICAL_PRODUCTS_PATH = Path(
    "data/canonical/core_products_v1.jsonl"
)


def test_reviewed_pool_has_thirty_independent_trajectories() -> None:
    trajectories = load_trajectory_pool(POOL_PATH)

    assert len(trajectories) >= 30
    assert all(len(item.turns) == 5 for item in trajectories)
    assert len({
        normalize_message(turn.message)
        for item in trajectories
        for turn in item.turns
    }) == len(trajectories) * 5
    assert no_simple_paraphrase_pairs(trajectories)


def test_reviewed_pool_matches_required_distribution() -> None:
    prefixes = Counter(
        trajectory.trajectory_id.split("-", maxsplit=1)[0]
        for trajectory in load_trajectory_pool(POOL_PATH)
    )

    assert prefixes == {
        "shop": 8,
        "knowledge": 5,
        "consult": 5,
        "image": 5,
        "recovery": 4,
        "isolation": 3,
    }


def test_frozen_set_has_twenty_independent_five_turn_trajectories() -> None:
    trajectories = load_frozen_trajectories(
        FROZEN_PATH,
        manifest_path=MANIFEST_PATH,
    )

    assert len(trajectories) == 20
    assert all(len(item.turns) == 5 for item in trajectories)
    assert len({
        normalize_message(turn.message)
        for item in trajectories
        for turn in item.turns
    }) == 100
    assert no_simple_paraphrase_pairs(trajectories)
    assert all(item.subject_scope == "self" for item in trajectories)
    assert all(
        "other" not in turn.acceptable_semantic.subject_scope_hints
        for item in trajectories
        for turn in item.turns
    )


def test_frozen_set_covers_all_stateful_route_families() -> None:
    families = {
        family
        for item in load_frozen_trajectories(
            FROZEN_PATH,
            manifest_path=MANIFEST_PATH,
        )
        for family in item.route_families
    }

    assert {
        "recommendation_revision",
        "product_followup",
        "general_knowledge_return",
        "comparison",
        "consultation_profile",
        "image_identity",
        "image_similarity",
        "clarification_recovery",
        "safety_escalation",
        "pending_turn",
    } <= families


def test_frozen_fixture_matches_seeded_selection_and_manifest() -> None:
    pool = load_trajectory_pool(POOL_PATH)
    selected = select_backend_trajectories(pool)
    frozen = load_frozen_trajectories(
        FROZEN_PATH,
        manifest_path=MANIFEST_PATH,
    )

    assert BACKEND_SELECTION_SEED == 2026081701
    assert frozen == selected
    assert build_continuous_fixture_manifest(
        pool_bytes=POOL_PATH.read_bytes(),
        selected_bytes=FROZEN_PATH.read_bytes(),
        pool=pool,
        selected=selected,
    ).model_dump_json(indent=2) + "\n" == (
        MANIFEST_PATH.read_text(encoding="utf-8")
    )


def test_hard_exclusion_trajectory_fails_closed_before_withdrawal() -> None:
    trajectories = {
        item.trajectory_id: item
        for item in load_trajectory_pool(POOL_PATH)
    }
    turns = trajectories["shop-exclusion-withdrawal"].turns

    assert turns[0].expected_card_ids == ()
    assert turns[0].expected_snapshot_subset["empty_result"] is True
    assert turns[0].expected_snapshot_subset["query_context"] == {
        "exclusions": ["酒精"],
    }
    assert turns[1].expected_route.continuity == "withdraw"
    assert turns[1].expected_card_ids == (38, 91)
    assert turns[4].expected_bindings[0].product_id == 34
    assert turns[4].expected_card_ids == (34,)


def test_image_budget_adjustment_retains_similarity_presentation() -> None:
    trajectories = {
        item.trajectory_id: item
        for item in load_trajectory_pool(POOL_PATH)
    }
    turns = trajectories["image-budget-similarity"].turns

    assert turns[2].expected_presentation_mode == (
        "image_recommendation"
    )
    assert turns[3].expected_presentation_mode == (
        "image_recommendation"
    )


def test_image_identity_expectations_follow_focus_and_presentation_contract(
) -> None:
    trajectories = load_trajectory_pool(POOL_PATH)

    for trajectory in trajectories:
        for turn in trajectory.turns:
            if turn.expected_route.processor != "image_identity":
                continue
            assert turn.expected_presentation_mode == "image_identity"
            current_product_id = (
                turn.expected_snapshot_subset
                .get("focus_state", {})
                .get("current_product_id")
            )
            assert current_product_id == (
                turn.expected_card_ids[0]
                if len(turn.expected_card_ids) == 1
                else None
            )


def test_fixed_budget_and_image_alternative_sets_use_business_facts(
) -> None:
    trajectories = {
        item.trajectory_id: item
        for item in load_trajectory_pool(POOL_PATH)
    }
    friend = trajectories["consult-friend-boundary"]
    assert friend.turns[2].expected_card_ids == (91,)
    assert set(friend.turns[4].expected_card_ids) == {33, 39, 91}

    image_budget = trajectories["image-budget-similarity"]
    assert [
        binding.product_id
        for binding in image_budget.turns[2].expected_bindings
    ] == [55]
    assert set(image_budget.turns[2].expected_card_ids) == {
        51,
        54,
        57,
    }
    assert set(image_budget.turns[3].expected_card_ids) == {
        51,
        53,
        57,
    }
    assert [
        binding.product_id
        for binding in image_budget.turns[4].expected_bindings
    ] == [57]

    image_count = trajectories["image-sunscreen-suitability"]
    assert image_count.turns[1].expected_presentation_mode == (
        "single_product"
    )
    assert image_count.turns[2].expected_presentation_mode == (
        "single_product"
    )
    assert [
        binding.product_id
        for binding in image_count.turns[3].expected_bindings
    ] == [53]
    assert image_count.turns[3].expected_route.continuity == (
        "supplement"
    )
    assert image_count.turns[3].expected_card_ids == (55, 57)
    assert {
        binding.product_id
        for binding in image_count.turns[4].expected_bindings
    } == {55, 57}

    sunscreen_loop = trajectories["knowledge-sunscreen-loop"]
    requested_two = sunscreen_loop.turns[1]
    assert requested_two.expected_card_ids == (56, 51)
    assert [
        binding.product_id
        for binding in sunscreen_loop.turns[2].expected_bindings
    ] == [51]
    assert sunscreen_loop.turns[2].expected_card_ids == (51,)
    assert [
        binding.product_id
        for binding in sunscreen_loop.turns[4].expected_bindings
    ] == [51]
    refreshing_products = {
        product_id
        for item in build_selection_concept_assets().projections
        if (
            item.profile.value == "suncare"
            and item.concept_id == "texture.refreshing"
        )
        for product_id in item.product_ids
    }
    reader = CanonicalProductReader.from_files(
        manifest_path=CANONICAL_MANIFEST_PATH,
        products_path=CANONICAL_PRODUCTS_PATH,
    )
    eligible_refreshing = {
        product_id: reader.get(product_id).fields["price"].value
        for product_id in refreshing_products
        if (
            reader.get(product_id).fields["price"].value is not None
            and reader.get(product_id).fields["price"].value <= 200
        )
    }
    assert sorted(
        eligible_refreshing,
        key=lambda product_id: (
            -eligible_refreshing[product_id],
            product_id,
        ),
    )[:2] == [56, 51]

    clarification = trajectories["image-clarify-and-recover"]
    assert clarification.turns[2].expected_presentation_mode == (
        "single_product"
    )
    assert [
        binding.product_id
        for binding in clarification.turns[3].expected_bindings
    ] == [55]
    assert clarification.turns[3].expected_route.continuity == (
        "supplement"
    )
    assert set(clarification.turns[3].expected_card_ids) == {
        51,
        54,
        57,
    }

    for product_id in (51, 54, 57):
        price = reader.get(product_id).fields["price"].value
        assert price is not None
        assert price <= 100

    safety = trajectories["consult-safety-pivot"]
    assert safety.turns[2].expected_route.continuity == "continue"
    assert safety.turns[3].expected_route.continuity == "continue"


def test_image_derived_candidate_batch_uses_normal_comparison_contract(
) -> None:
    trajectories = {
        item.trajectory_id: item
        for item in load_trajectory_pool(POOL_PATH)
    }
    turn = trajectories["image-sunscreen-suitability"].turns[4]

    assert {
        binding.product_id for binding in turn.expected_bindings
    } == {55, 57}
    assert turn.expected_route.processor == "comparison"
    assert turn.expected_route.focus_source == "candidate_batch"
    assert turn.expected_presentation_mode == "comparison"


def test_direct_image_batch_comparison_uses_confirmed_image_authority(
) -> None:
    trajectories = {
        item.trajectory_id: item
        for item in load_trajectory_pool(POOL_PATH)
    }
    turn = trajectories["image-two-product-comparison"].turns[1]

    assert {
        binding.source_text for binding in turn.expected_bindings
    } == {"image_ordinal:1", "image_ordinal:2"}
    assert None in turn.acceptable_semantic.topic_hints
    assert turn.expected_route.processor == "comparison"
    assert turn.expected_route.focus_source == "confirmed_image"

    knowledge_turn = trajectories[
        "image-two-product-comparison"
    ].turns[3]
    assert "continue" in (
        knowledge_turn.acceptable_semantic.continuity_hints
    )
    assert knowledge_turn.expected_route.processor == "general_knowledge"
    assert knowledge_turn.expected_route.continuity == "replace_task"

    return_turn = trajectories[
        "image-two-product-comparison"
    ].turns[4]
    assert [
        binding.source_text
        for binding in return_turn.expected_bindings
    ] == ["image_ordinal:1"]
    assert return_turn.expected_route.continuity == "return_to_focus"
    assert return_turn.expected_route.focus_source == "confirmed_image"


def test_code_owned_general_knowledge_switch_accepts_raw_continue(
) -> None:
    turns = [
        turn
        for trajectory in load_trajectory_pool(POOL_PATH)
        if trajectory.subject_scope == "self"
        for index, turn in enumerate(trajectory.turns)
        if (
            index > 0
            and turn.expected_route.processor == "general_knowledge"
            and turn.expected_route.continuity == "replace_task"
            and not turn.expected_bindings
        )
    ]

    assert len(turns) == 13
    assert all(
        "continue" in turn.acceptable_semantic.continuity_hints
        for turn in turns
    )


def test_code_owned_named_comparison_switch_accepts_raw_continue(
) -> None:
    turns = [
        turn
        for trajectory in load_trajectory_pool(POOL_PATH)
        if trajectory.subject_scope == "self"
        for turn in trajectory.turns
        if (
            turn.expected_route.processor == "comparison"
            and turn.expected_route.continuity == "replace_task"
            and turn.expected_route.focus_source == "explicit_product"
        )
    ]

    assert len(turns) == 8
    assert all(
        "continue" in turn.acceptable_semantic.continuity_hints
        for turn in turns
    )


def test_code_owned_product_return_accepts_raw_continue() -> None:
    turns = [
        current
        for trajectory in load_trajectory_pool(POOL_PATH)
        if trajectory.subject_scope == "self"
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

    assert len(turns) == 9
    assert all(
        "continue" in turn.acceptable_semantic.continuity_hints
        for turn in turns
    )


def test_code_owned_correct_continuity_requires_recommendation_replacement(
) -> None:
    turns = [
        turn
        for trajectory in load_trajectory_pool(POOL_PATH)
        for turn in trajectory.turns
        if turn.expected_route.continuity == "correct"
    ]

    assert turns
    assert all(
        turn.expected_route.processor == "recommendation"
        for turn in turns
    )


def test_ambiguous_multi_image_clarification_preserves_resume_focus(
) -> None:
    trajectories = {
        item.trajectory_id: item
        for item in load_trajectory_pool(POOL_PATH)
    }
    turn = trajectories["image-clarify-and-recover"].turns[1]

    assert "image_identity" in turn.acceptable_semantic.operation_hints
    assert "followup" in turn.acceptable_semantic.operation_hints
    assert turn.expected_route.processor == "clarification"
    assert turn.expected_route.continuity == "continue"
    assert turn.expected_snapshot_subset == {
        "focus_state": {"active_processor": "image_identity"}
    }
    assert turn.expected_clarification
    assert turn.expected_bindings == ()


def test_initial_ambiguous_product_uses_typed_clarification_overlay(
) -> None:
    trajectories = {
        item.trajectory_id: item
        for item in load_trajectory_pool(POOL_PATH)
    }
    turn = trajectories["recovery-ambiguous-product"].turns[0]

    assert turn.expected_route.processor == "clarification"
    assert turn.expected_snapshot_subset == {
        "clarification": {
            "gap": "reference",
            "attempts": 1,
        }
    }
    recovery = trajectories["recovery-ambiguous-product"].turns[1]
    assert "clarification" in (
        recovery.acceptable_semantic.operation_hints
    )
    assert recovery.expected_route.processor == "product_knowledge"
    assert recovery.expected_task_plan_subset["mode"] == "knowledge"


def test_clarification_expectations_use_typed_overlay_not_fake_focus(
) -> None:
    trajectories = load_trajectory_pool(POOL_PATH)
    clarification_turns = [
        turn
        for trajectory in trajectories
        for turn in trajectory.turns
        if turn.expected_clarification
    ]

    assert clarification_turns
    assert all(
        turn.expected_snapshot_subset
        .get("focus_state", {})
        .get("active_processor")
        != "clarification"
        for turn in clarification_turns
    )
    budget_turns = [
        turn
        for turn in clarification_turns
        if "预算" in turn.message or "两三百" in turn.message
    ]
    assert budget_turns
    assert all(
        turn.expected_snapshot_subset["clarification"]["gap"]
        == "budget"
        for turn in budget_turns
    )


def test_pending_turn_expectations_preserve_and_resume_original_task(
) -> None:
    trajectories = {
        item.trajectory_id: item
        for item in load_trajectory_pool(POOL_PATH)
    }
    affirm = trajectories["recovery-pending-affirm"]
    first, second = affirm.turns[:2]

    assert first.expected_snapshot_subset["pending_turn"] == {
        "gap": "budget",
        "resume_mode": "recommendation",
        "resume_context": {"category": "serum"},
    }
    assert "clarification" in second.acceptable_semantic.operation_hints
    assert None in second.acceptable_semantic.topic_hints
    assert second.expected_route.processor == "recommendation"
    assert second.expected_route.continuity == "correct"
    budget_revision = affirm.turns[3]
    assert budget_revision.message == "再把预算降到两百"
    assert budget_revision.expected_card_ids == (91,)
    assert budget_revision.expected_snapshot_subset["query_context"] == {
        "budget_maximum": "200",
    }

    correction = trajectories["recovery-pending-correct"]
    first, rejected, resumed = correction.turns[:3]
    assert first.expected_snapshot_subset["pending_turn"]["gap"] == "budget"
    assert rejected.expected_route.processor == "clarification"
    assert rejected.expected_route.continuity == "continue"
    assert rejected.expected_snapshot_subset["pending_turn"] == {
        "gap": "budget",
        "attempts": 2,
        "expected_response": "supply_value",
        "resume_mode": "recommendation",
        "resume_context": {"category": "serum"},
    }
    assert resumed.expected_route.processor == "recommendation"
    assert resumed.expected_route.continuity == "correct"
    assert set(resumed.acceptable_semantic.topic_hints) == {
        "serum",
        "skincare",
        None,
    }
    assert resumed.expected_task_plan_subset["mode"] == "recommend"
    supplemented, followup = correction.turns[3:5]
    assert set(supplemented.expected_card_ids) == {38, 91}
    assert followup.message.startswith("第二款")
    assert [
        binding.product_id for binding in followup.expected_bindings
    ] == [38]
    assert followup.expected_card_ids == (38,)
    assert followup.expected_snapshot_subset["focus_state"][
        "current_product_id"
    ] == 38


def test_return_after_knowledge_uses_latest_recommendation_order() -> None:
    trajectories = {
        item.trajectory_id: item
        for item in load_trajectory_pool(POOL_PATH)
    }
    trajectory = trajectories["shop-comparison-course-change"]
    revision = trajectory.turns[2]
    detour = trajectory.turns[3]
    returned = trajectory.turns[4]

    assert revision.expected_route.continuity == "supplement"
    assert set(revision.expected_card_ids) == {38, 91}
    assert detour.expected_route.processor == "general_knowledge"
    assert returned.expected_route.continuity == "return_to_focus"
    assert [
        binding.product_id for binding in returned.expected_bindings
    ] == [91]
    assert returned.expected_card_ids == (91,)
    assert returned.expected_snapshot_subset["focus_state"][
        "current_product_id"
    ] == 91


def test_anti_aging_budget_filters_before_condition_reset() -> None:
    trajectories = {
        item.trajectory_id: item
        for item in load_trajectory_pool(POOL_PATH)
    }
    first, reset = trajectories["shop-condition-reset"].turns[:2]

    assert first.message == "四百以内找抗老精华，我偏干还容易泛红"
    assert first.expected_card_ids == (42,)
    assert reset.message == "抗老先撤掉，改成保湿修护优先"
    assert set(reset.expected_card_ids) == {38, 91}
    followup = trajectories["shop-condition-reset"].turns[2]
    returned = trajectories["shop-condition-reset"].turns[4]
    assert followup.message.startswith("第二款")
    assert [
        binding.product_id for binding in followup.expected_bindings
    ] == [38]
    assert followup.expected_card_ids == (38,)
    assert [
        binding.product_id for binding in returned.expected_bindings
    ] == [38]
    assert returned.expected_card_ids == (38,)


def test_efficacy_shopping_pivot_uses_broad_skincare_not_serum(
) -> None:
    trajectories = {
        item.trajectory_id: item
        for item in load_trajectory_pool(POOL_PATH)
    }
    turn = trajectories["consult-correction"].turns[4]

    assert turn.message == "先按修护和保湿优先，预算二百"
    assert set(turn.acceptable_semantic.topic_hints) == {
        "skincare",
        None,
    }
    assert "serum" not in turn.acceptable_semantic.topic_hints
    assert "continue" in turn.acceptable_semantic.continuity_hints
    assert turn.expected_route.processor == "recommendation"
    assert turn.expected_route.continuity == "replace_task"
    assert turn.expected_task_plan_subset == {"mode": "recommend"}
    assert turn.expected_snapshot_subset == {
        "query_context": {
            "category": "skincare",
            "budget_maximum": "200",
            "efficacy": "repair",
            "concepts": [
                {
                    "field_key": "efficacy",
                    "concept_id": "efficacy.hydration",
                    "polarity": "prefer",
                },
                {
                    "field_key": "efficacy",
                    "concept_id": "efficacy.repair",
                    "polarity": "prefer",
                },
            ],
        },
        "focus_state": {"active_processor": "recommendation"},
    }
    assert set(turn.expected_card_ids) == {91, 93, 131}
    assert not turn.expected_clarification
    assert turn.expected_presentation_mode == "recommendation"

    projections = build_selection_concept_assets().projections
    assert {
        item.concept_id
        for item in projections
        if (
            item.profile.value == "skincare"
            and item.field_key == "efficacy"
            and item.normalized_value == "保湿"
        )
    } == {"efficacy.hydration"}

    reader = CanonicalProductReader.from_files(
        manifest_path=CANONICAL_MANIFEST_PATH,
        products_path=CANONICAL_PRODUCTS_PATH,
    )
    for product_id in turn.expected_card_ids:
        product = reader.get(product_id)
        assert product.fields["price"].value <= 200
    assert set(reader.get(131).fields["efficacy"].value) >= {
        "保湿",
        "修护",
    }


def test_consultation_to_recommendation_accepts_context_continuity(
) -> None:
    fixture_sets = (
        (load_trajectory_pool(POOL_PATH), 7),
        (
            load_frozen_trajectories(
                FROZEN_PATH,
                manifest_path=MANIFEST_PATH,
            ),
            4,
        ),
    )
    for trajectories, expected_count in fixture_sets:
        pivots = []
        for trajectory in trajectories:
            for previous, current in zip(
                trajectory.turns,
                trajectory.turns[1:],
            ):
                if (
                    previous.expected_route.processor
                    == "consultation"
                    and current.expected_route.processor
                    == "recommendation"
                ):
                    pivots.append(current)

        assert len(pivots) == expected_count
        for turn in pivots:
            assert {
                "new_task",
                "continue",
            } <= set(
                turn.acceptable_semantic.continuity_hints
            )
            assert turn.expected_route.continuity == "replace_task"


def test_named_product_detour_preserves_consultation_for_return(
) -> None:
    trajectories = {
        item.trajectory_id: item
        for item in load_trajectory_pool(POOL_PATH)
    }
    detour = trajectories["consult-product-interruption"].turns[2]
    resumed = trajectories["consult-product-interruption"].turns[3]

    assert detour.message.startswith("先插一句")
    assert detour.acceptable_semantic.continuity_hints == (
        "continue",
        "unknown",
    )
    assert detour.expected_route.processor == "product_knowledge"
    assert detour.expected_route.continuity == "continue"
    assert resumed.acceptable_semantic.continuity_hints == (
        "return_to_focus",
    )
    assert resumed.expected_route.processor == "consultation"
    assert resumed.expected_route.continuity == "return_to_focus"


def test_lightweight_repair_selection_uses_reviewed_concepts(
) -> None:
    trajectories = {
        item.trajectory_id: item
        for item in load_trajectory_pool(POOL_PATH)
    }
    turn = trajectories["consult-product-interruption"].turns[4]

    assert turn.message == "按目前观察给我选轻薄修护精华"
    assert set(turn.expected_card_ids) == {38, 39, 91}

    projections = build_selection_concept_assets().projections
    lightweight_products = {
        product_id
        for item in projections
        if (
            item.profile.value == "skincare"
            and item.concept_id == "texture.lightweight"
        )
        for product_id in item.product_ids
    }
    assert {39, 91} <= lightweight_products

    reader = CanonicalProductReader.from_files(
        manifest_path=CANONICAL_MANIFEST_PATH,
        products_path=CANONICAL_PRODUCTS_PATH,
    )
    product = reader.get(39)
    assert product.fields["category"].value == "精华"
    assert "修护" in product.fields["efficacy"].value
