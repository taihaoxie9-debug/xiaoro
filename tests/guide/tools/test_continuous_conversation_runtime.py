from __future__ import annotations

import json
from pathlib import Path

from app.guide.application.contracts import TurnIdentity
from app.guide.understanding.turn_meaning_contracts import TurnMeaning
from tools.guide_gates.continuous_conversation_gate import (
    ContinuousTrajectory,
    execute_continuous_trajectory,
)
from tools.guide_gates.continuous_conversation_fixture import (
    load_frozen_trajectories,
)
from tools.guide_gates.continuous_conversation_runtime import (
    build_local_continuous_runtime,
)


_MESSAGES = (
    "防晒为什么需要补涂",
    "烟酰胺主要有什么作用",
    "敏感肌和过敏怎么区分",
    "A醇为什么要建立耐受",
    "油皮为什么也会缺水",
)


def _trajectory() -> ContinuousTrajectory:
    return ContinuousTrajectory.model_validate(
        {
            "trajectory_id": "runtime-general-knowledge",
            "subject_scope": "self",
            "route_families": ["general_knowledge_return"],
            "turns": [
                {
                    "turn_id": f"runtime-general-knowledge-t{index}",
                    "message": message,
                    "acceptable_semantic": {
                        "operation_hints": ["knowledge"],
                        "topic_hints": [topic],
                        "continuity_hints": ["new_task"],
                        "subject_scope_hints": ["self"],
                    },
                    "expected_bindings": [],
                    "expected_route": {
                        "processor": "general_knowledge",
                        "continuity": "replace_task",
                        "focus_source": "knowledge_topic",
                    },
                    "expected_snapshot_subset": {
                        "active_owner": "general_knowledge",
                        "active_focus": {"slot": "knowledge"},
                    },
                    "expected_task_plan_subset": {},
                    "expected_card_ids": [],
                    "expected_safety": False,
                    "expected_clarification": False,
                    "expected_presentation_mode": "general_knowledge",
                    "public_answer_policy": "general_knowledge",
                }
                for index, (message, topic) in enumerate(
                    zip(
                        _MESSAGES,
                        (
                            "sunscreen",
                            "serum",
                            "skincare",
                            "skincare",
                            "skincare",
                        ),
                        strict=True,
                    ),
                    start=1,
                )
            ],
        },
        strict=True,
    )


def _meanings() -> tuple[TurnMeaning, ...]:
    return tuple(
        TurnMeaning.model_validate(
            {
                "operation_hint": "knowledge",
                "topic_hint": topic,
                "continuity_hint": "new_task",
                "subject_scope_hint": "self",
                "reference_mentions": [],
                "product_mentions": [],
                "budget_candidates": [],
                "observation_candidates": [],
                "preference_candidates": [],
                "relative_candidates": [],
                "consultation_hypothesis": None,
                "next_observation_gap": None,
                "question_meaning": message,
                "safety_language": "ordinary",
            },
            strict=True,
        )
        for message, topic in zip(
            _MESSAGES,
            (
                "sunscreen",
                "serum",
                "skincare",
                "skincare",
                "skincare",
            ),
            strict=True,
        )
    )


def test_local_runtime_executes_five_real_sequential_sse_turns(
    tmp_path: Path,
) -> None:
    trajectory = _trajectory()
    runtime = build_local_continuous_runtime(
        trajectory,
        tmp_path / "state",
        repo_root=Path.cwd(),
    )

    trace = execute_continuous_trajectory(
        trajectory,
        runtime=runtime,
        meanings=_meanings(),
    )

    assert [turn.starting_version for turn in trace.turns] == [
        0, 1, 2, 3, 4,
    ]
    assert [turn.terminal_version for turn in trace.turns] == [
        1, 2, 3, 4, 5,
    ]
    assert all(
        turn.route.processor == "general_knowledge"
        for turn in trace.turns
    )
    assert all(
        turn.presentation_mode == "general_knowledge"
        for turn in trace.turns
    )
    assert all(turn.public_messages for turn in trace.turns)
    identities = runtime._observer.turn_identities
    assert len(identities) == 5
    assert all(type(identity) is TurnIdentity for identity in identities)
    assert {
        identity.session_id for identity in identities
    } == {trajectory.trajectory_id}
    assert len({identity.request_id for identity in identities}) == 5
    assert len({identity.turn_id for identity in identities}) == 5
    assert all(
        len(identity.request_id) >= 16
        and len(identity.turn_id) >= 16
        and identity.request_id != identity.turn_id
        for identity in identities
    )
    registry = runtime._vertical.unified._processor_registry
    assert registry["image_identity"] is runtime._vertical.image_processor
    assert registry["image_comparison"] is runtime._vertical.image_processor
    assert not hasattr(runtime, "_image_processor")


def _consultation_meaning(
    *,
    continuity: str,
    observations: tuple[dict[str, object], ...] = (),
    conditions: tuple[str, ...] = (),
    support: tuple[str, ...] = (),
    next_gap: str | None = None,
    operation: str = "assessment",
    safety_language: str = "ordinary",
) -> TurnMeaning:
    return TurnMeaning.model_validate(
        {
            "operation_hint": operation,
            "topic_hint": "skincare",
            "continuity_hint": continuity,
            "subject_scope_hint": "self",
            "reference_mentions": [],
            "product_mentions": [],
            "budget_candidates": [],
            "observation_candidates": list(observations),
            "preference_candidates": [],
            "relative_candidates": [],
            "consultation_hypothesis": (
                {
                    "base_skin_direction": None,
                    "stable_tendencies": [],
                    "current_conditions": list(conditions),
                    "supporting_observation_ids": list(support),
                }
                if conditions
                else None
            ),
            "next_observation_gap": next_gap,
            "question_meaning": "继续判断当前皮肤状态",
            "safety_language": safety_language,
        },
        strict=True,
    )


def _dynamic_observation(
    observation_id: str,
    *,
    code: str,
    raw_text: str,
    present: bool = True,
    trigger: str | None = None,
    duration: str | None = None,
    severity: str | None = None,
) -> dict[str, object]:
    return {
        "observation_id": observation_id,
        "code": code,
        "present": present,
        "qualifier": None,
        "raw_text": raw_text,
        "location": None,
        "trigger": trigger,
        "duration": duration,
        "severity": severity,
    }


def test_local_runtime_safety_pivot_advances_once_per_real_turn(
    tmp_path: Path,
) -> None:
    trajectory = next(
        item
        for item in load_frozen_trajectories()
        if item.trajectory_id == "consult-safety-pivot"
    )
    meanings = (
        _consultation_meaning(
            continuity="new_task",
            observations=(
                _dynamic_observation(
                    "obs_heat",
                    code="burning",
                    raw_text="发热",
                    trigger="ordinary_skincare",
                    duration="recurrent",
                    severity="mild",
                ),
                _dynamic_observation(
                    "obs_redness",
                    code="redness",
                    raw_text="泛红",
                    trigger="ordinary_skincare",
                    duration="recurrent",
                    severity="mild",
                ),
            ),
            conditions=("redness",),
            support=("obs_redness",),
            next_gap="active_damage_risk",
        ),
        _consultation_meaning(
            continuity="continue",
            observations=(
                _dynamic_observation(
                    "obs_damage",
                    code="broken_skin",
                    raw_text="没有破皮",
                    present=False,
                ),
            ),
            next_gap="location",
        ),
        _consultation_meaning(
            continuity="continue",
            observations=(
                _dynamic_observation(
                    "obs_damage_now",
                    code="broken_skin",
                    raw_text="有一块破了",
                    severity="moderate",
                ),
                _dynamic_observation(
                    "obs_oozing",
                    code="oozing",
                    raw_text="往外渗液",
                    severity="moderate",
                ),
            ),
            conditions=("broken_skin", "oozing"),
            support=("obs_damage_now", "obs_oozing"),
            safety_language="safety",
        ),
        _consultation_meaning(
            continuity="continue",
            observations=(
                _dynamic_observation(
                    "obs_oozing_now",
                    code="oozing",
                    raw_text="仍然在渗",
                    severity="moderate",
                ),
                _dynamic_observation(
                    "obs_pain",
                    code="pain",
                    raw_text="会疼",
                    severity="moderate",
                ),
            ),
            conditions=("oozing", "persistent_pain"),
            support=("obs_oozing_now", "obs_pain"),
            safety_language="safety",
        ),
        _consultation_meaning(
            continuity="new_task",
            operation="knowledge",
        ),
    )
    runtime = build_local_continuous_runtime(
        trajectory,
        tmp_path / "safety-state",
        repo_root=Path.cwd(),
    )

    trace = execute_continuous_trajectory(
        trajectory,
        runtime=runtime,
        meanings=meanings,
    )

    assert [turn.starting_version for turn in trace.turns] == [
        0, 1, 2, 3, 4,
    ]
    assert [turn.terminal_version for turn in trace.turns] == [
        1, 2, 3, 4, 5,
    ]
    assert trace.turns[2].route.processor == "safety_escalation"
    assert trace.turns[3].route.processor == "safety_escalation"
    assert trace.turns[2].safety is True
    assert trace.turns[3].safety is True


def test_local_runtime_product_interruption_returns_to_consultation(
    tmp_path: Path,
) -> None:
    trajectory = next(
        item
        for item in load_frozen_trajectories()
        if item.trajectory_id == "consult-product-interruption"
    )
    captured = tuple(
        TurnMeaning.model_validate(payload, strict=True)
        for payload in (
            {
                "operation_hint": "assessment",
                "topic_hint": None,
                "continuity_hint": "new_task",
                "subject_scope_hint": "self",
                "reference_mentions": [],
                "product_mentions": [],
                "budget_candidates": [],
                "observation_candidates": [
                    {
                        "observation_id": "obs_oiliness",
                        "code": "oiliness",
                        "present": True,
                        "qualifier": None,
                        "raw_text": "下午会油",
                        "location": None,
                        "trigger": None,
                        "duration": "recurrent",
                        "severity": None,
                    },
                    {
                        "observation_id": "obs_dryness",
                        "code": "dryness",
                        "present": True,
                        "qualifier": None,
                        "raw_text": "空调房又干",
                        "location": None,
                        "trigger": None,
                        "duration": "current",
                        "severity": None,
                    },
                ],
                "preference_candidates": [],
                "relative_candidates": [],
                "consultation_hypothesis": {
                    "base_skin_direction": "combination",
                    "stable_tendencies": [],
                    "current_conditions": [],
                    "supporting_observation_ids": [
                        "obs_oiliness",
                        "obs_dryness",
                    ],
                },
                "next_observation_gap": "location",
                "question_meaning": "判断肤质",
                "safety_language": "ordinary",
            },
            {
                "operation_hint": "assessment",
                "topic_hint": None,
                "continuity_hint": "continue",
                "subject_scope_hint": "self",
                "reference_mentions": [],
                "product_mentions": [],
                "budget_candidates": [],
                "observation_candidates": [
                    {
                        "observation_id": "obs_oiliness",
                        "code": "oiliness",
                        "present": True,
                        "qualifier": None,
                        "raw_text": "油主要在鼻子",
                        "location": "nose",
                        "trigger": None,
                        "duration": "recurrent",
                        "severity": None,
                    },
                ],
                "preference_candidates": [],
                "relative_candidates": [],
                "consultation_hypothesis": {
                    "base_skin_direction": "combination",
                    "stable_tendencies": [],
                    "current_conditions": [],
                    "supporting_observation_ids": ["obs_oiliness"],
                },
                "next_observation_gap": "persistence_or_trigger",
                "question_meaning": "补充部位",
                "safety_language": "ordinary",
            },
            {
                "operation_hint": "knowledge",
                "topic_hint": "serum",
                "continuity_hint": "new_task",
                "subject_scope_hint": "self",
                "reference_mentions": [
                    {
                        "raw_text": "B5精华",
                        "object_family_hint": "product",
                        "ordinal_hint": None,
                        "plurality_hint": "single",
                    }
                ],
                "product_mentions": [{"raw_text": "B5精华"}],
                "budget_candidates": [],
                "observation_candidates": [],
                "preference_candidates": [],
                "relative_candidates": [],
                "consultation_hypothesis": None,
                "next_observation_gap": None,
                "question_meaning": "B5精华能否使用",
                "safety_language": "ordinary",
            },
            {
                "operation_hint": "assessment",
                "topic_hint": "serum",
                "continuity_hint": "return_to_focus",
                "subject_scope_hint": "self",
                "reference_mentions": [],
                "product_mentions": [],
                "budget_candidates": [],
                "observation_candidates": [
                    {
                        "observation_id": "obs_comedones",
                        "code": "oiliness",
                        "present": True,
                        "qualifier": "recurrent",
                        "raw_text": "闷痘",
                        "location": None,
                        "trigger": None,
                        "duration": "recurrent",
                        "severity": None,
                    },
                ],
                "preference_candidates": [],
                "relative_candidates": [],
                "consultation_hypothesis": None,
                "next_observation_gap": "persistence_or_trigger",
                "question_meaning": "回到肤质判断",
                "safety_language": "ordinary",
            },
            {
                "operation_hint": "recommendation",
                "recommendation_mode": "explore",
                "recommendation_mode_basis": {
                    "basis": "broad_exploration",
                    "source_text": "选",
                },
                "topic_hint": "serum",
                "continuity_hint": "new_task",
                "subject_scope_hint": "self",
                "reference_mentions": [],
                "product_mentions": [],
                "budget_candidates": [],
                "observation_candidates": [],
                "preference_candidates": [],
                "relative_candidates": [],
                "consultation_hypothesis": None,
                "next_observation_gap": None,
                "question_meaning": "按肤质推荐修护精华",
                "safety_language": "ordinary",
            },
        )
    )
    runtime = build_local_continuous_runtime(
        trajectory,
        tmp_path / "product-interruption-state",
        repo_root=Path.cwd(),
    )

    trace = execute_continuous_trajectory(
        trajectory,
        runtime=runtime,
        meanings=captured,
    )

    assert [turn.terminal_version for turn in trace.turns] == [
        1, 2, 3, 4, 5,
    ]
    # Turn 3 is a product-knowledge interruption on B5 (id 38).
    assert trace.turns[2].route.processor == "product_knowledge"
    assert trace.turns[2].card_ids == (38,)
    # Turn 4 "回到肤质判断" must restore consultation, not the stale product.
    assert trace.turns[3].route.processor == "consultation"
    assert trace.turns[3].card_ids == ()
    assert trace.turns[3].bindings == ()


def test_local_runtime_image_followup_presents_product_knowledge(
    tmp_path: Path,
) -> None:
    trajectory = next(
        item
        for item in load_frozen_trajectories()
        if item.trajectory_id == "image-budget-similarity"
    )
    identify = TurnMeaning.model_validate(
        {
            "operation_hint": "image_identity",
            "topic_hint": "sunscreen",
            "continuity_hint": "new_task",
            "subject_scope_hint": "self",
            "reference_mentions": [
                {
                    "raw_text": "照片",
                    "object_family_hint": "image",
                    "ordinal_hint": None,
                    "plurality_hint": "batch",
                }
            ],
            "product_mentions": [{"raw_text": "清透防晒乳"}],
            "budget_candidates": [],
            "observation_candidates": [],
            "preference_candidates": [],
            "relative_candidates": [],
            "consultation_hypothesis": None,
            "next_observation_gap": None,
            "question_meaning": "识别照片里的清透防晒乳",
            "safety_language": "ordinary",
        },
        strict=True,
    )
    followup = TurnMeaning.model_validate(
        {
            "operation_hint": "followup",
            "topic_hint": None,
            "continuity_hint": "continue",
            "subject_scope_hint": "self",
            "reference_mentions": [
                {
                    "raw_text": "它",
                    "object_family_hint": "image",
                    "ordinal_hint": 1,
                    "plurality_hint": "single",
                }
            ],
            "product_mentions": [],
            "budget_candidates": [],
            "observation_candidates": [],
            "preference_candidates": [],
            "relative_candidates": [],
            "consultation_hypothesis": None,
            "next_observation_gap": None,
            "question_meaning": "它的参考价后面为什么没有规格",
            "safety_language": "ordinary",
        },
        strict=True,
    )
    filler = TurnMeaning.model_validate(
        {
            "operation_hint": "knowledge",
            "topic_hint": "sunscreen",
            "continuity_hint": "continue",
            "subject_scope_hint": "self",
            "reference_mentions": [],
            "product_mentions": [],
            "budget_candidates": [],
            "observation_candidates": [],
            "preference_candidates": [],
            "relative_candidates": [],
            "consultation_hypothesis": None,
            "next_observation_gap": None,
            "question_meaning": "补涂知识",
            "safety_language": "ordinary",
        },
        strict=True,
    )
    meanings = (identify, followup, filler, filler, filler)
    runtime = build_local_continuous_runtime(
        trajectory,
        tmp_path / "image-followup-state",
        repo_root=Path.cwd(),
    )

    trace = execute_continuous_trajectory(
        trajectory,
        runtime=runtime,
        meanings=meanings,
    )

    # Turn 2 is a followup about the confirmed image product; it must present
    # product knowledge, not be rejected as a contract-invalid recommendation.
    assert trace.turns[1].route.processor == "product_knowledge"
    assert trace.turns[1].card_ids == (55,)
    assert trace.turns[1].presentation_mode == "product_knowledge"
    assert "error" not in trace.turns[1].event_names


def test_local_runtime_keeps_image_presentation_after_budget_revision(
    tmp_path: Path,
) -> None:
    trajectory = next(
        item
        for item in load_frozen_trajectories()
        if item.trajectory_id == "image-budget-similarity"
    )
    similarity_message = (
        "以照片里的清透防晒乳为参照找相似方向，"
        "但预算必须在一百以内"
    )
    trajectory = trajectory.model_copy(
        update={
            "turns": (
                *trajectory.turns[:2],
                trajectory.turns[2].model_copy(
                    update={"message": similarity_message},
                    deep=True,
                ),
                *trajectory.turns[3:],
            ),
        },
        deep=True,
    )

    def meaning(**updates: object) -> TurnMeaning:
        payload: dict[str, object] = {
            "operation_hint": "recommendation",
            "topic_hint": "sunscreen",
            "continuity_hint": "continue",
            "subject_scope_hint": "self",
            "reference_mentions": [],
            "product_mentions": [],
            "budget_candidates": [],
            "observation_candidates": [],
            "preference_candidates": [],
            "relative_candidates": [],
            "consultation_hypothesis": None,
            "next_observation_gap": None,
            "question_meaning": None,
            "safety_language": "ordinary",
        }
        payload.update(updates)
        return TurnMeaning.model_validate(payload, strict=True)

    meanings = (
        meaning(
            operation_hint="image_identity",
            continuity_hint="new_task",
            reference_mentions=[{
                "raw_text": "照片",
                "object_family_hint": "image",
                "ordinal_hint": None,
                "plurality_hint": "batch",
            }],
            product_mentions=[{"raw_text": "清透防晒乳"}],
            question_meaning="识别照片里的清透防晒乳",
        ),
        meaning(
            operation_hint="followup",
            topic_hint=None,
            reference_mentions=[{
                "raw_text": "它",
                "object_family_hint": "image",
                "ordinal_hint": 1,
                "plurality_hint": "single",
            }],
            question_meaning="核对图片商品的规格",
        ),
        meaning(
            operation_hint="image_similarity",
            recommendation_mode="explore",
            recommendation_mode_basis={
                "basis": "similar_alternatives",
                "source_text": "相似",
            },
            reference_mentions=[{
                "raw_text": "照片里的清透防晒乳",
                "object_family_hint": "image",
                "ordinal_hint": 1,
                "plurality_hint": "single",
            }],
            product_mentions=[{"raw_text": "清透防晒乳"}],
            budget_candidates=[{
                "raw_text": "一百以内",
                "relation": "maximum",
                "minimum": None,
                "maximum": "100",
            }],
            question_meaning=similarity_message,
        ),
        meaning(
            recommendation_mode="explore",
            recommendation_mode_basis={
                "basis": "bounded_exploration",
                "source_text": "预算放到一百五",
            },
            budget_candidates=[{
                "raw_text": "一百五",
                "relation": "maximum",
                "minimum": None,
                "maximum": "150",
            }],
            preference_candidates=[{
                "field_key": "texture",
                "concept_id": "texture.refreshing",
                "raw_text": "清爽",
                "polarity": "prefer",
                "strength": "ordinary",
            }],
            question_meaning="预算改为一百五并保持清爽通勤",
        ),
        meaning(
            operation_hint="followup",
            reference_mentions=[{
                "raw_text": "第二款",
                "object_family_hint": "product",
                "ordinal_hint": 2,
                "plurality_hint": "single",
            }],
            question_meaning="询问新结果的第二款",
        ),
    )
    runtime = build_local_continuous_runtime(
        trajectory,
        tmp_path / "image-budget-revision-state",
        repo_root=Path.cwd(),
    )

    trace = execute_continuous_trajectory(
        trajectory,
        runtime=runtime,
        meanings=meanings,
    )

    similarity = trace.turns[2]
    assert similarity.event_names[-1] == "end"
    assert "error" not in similarity.event_names
    assert similarity.route.focus_source == "confirmed_image"
    assert similarity.final_snapshot.recommendation_slot is not None
    assert (
        similarity.final_snapshot.recommendation_slot.query_context
        .similarity_anchor_product_id
        == 55
    )
    revision = trace.turns[3]
    assert revision.route.continuity == "correct"
    assert len(revision.card_ids) == 3
    assert 55 not in revision.card_ids
    assert revision.final_snapshot.recommendation_slot is not None
    assert tuple(
        item.product_id
        for item in revision.final_snapshot.recommendation_slot.candidates
    ) == revision.card_ids
    assert revision.presentation_mode == "recommendation"
    assert (
        revision.final_snapshot.recommendation_slot.query_context
        .similarity_anchor_product_id
        == 55
    )
    assert trace.turns[4].bindings[0].product_id == (
        revision.card_ids[1]
    )


def _image_trajectory() -> ContinuousTrajectory:
    payload = _trajectory().model_dump(mode="json")
    payload["trajectory_id"] = "runtime-image-identity"
    payload["route_families"] = ["image_identity"]
    payload["turns"][0] = {
        "turn_id": "runtime-image-identity-t1",
        "message": "帮我确认图片里的防晒是什么",
        "image_fixture_ids": ["product-53-front"],
        "acceptable_semantic": {
            "operation_hints": ["image_identity"],
            "topic_hints": ["sunscreen"],
            "continuity_hints": ["new_task"],
            "subject_scope_hints": ["self"],
        },
        "expected_bindings": [
            {
                "product_id": 53,
                "variant_scope": None,
                "source_text": "image_ordinal:1",
            }
        ],
        "expected_route": {
            "processor": "image_identity",
            "continuity": "replace_task",
            "focus_source": "confirmed_image",
        },
        "expected_snapshot_subset": {
            "active_owner": "image_identity",
            "active_focus": {
                "slot": "image",
                "object_id": 53,
                "ordinal": 1,
            },
            "image_slot": {
                "kind": "image",
                "confirmed_products": [{
                    "image_ordinal": 1,
                    "product_id": 53,
                    "variant_scope": None,
                }],
                "focused_image_ordinal": 1,
            },
        },
        "expected_task_plan_subset": {},
        "expected_card_ids": [53],
        "expected_safety": False,
        "expected_clarification": False,
        "expected_presentation_mode": "image_identity",
        "public_answer_policy": "product_knowledge",
    }
    for index, turn in enumerate(payload["turns"][1:], start=2):
        turn["turn_id"] = f"runtime-image-identity-t{index}"
    return ContinuousTrajectory.model_validate(payload, strict=True)


def test_local_runtime_materializes_real_image_fixture(
    tmp_path: Path,
) -> None:
    trajectory = _image_trajectory()
    meanings = list(_meanings())
    meanings[0] = TurnMeaning.model_validate(
        {
            "operation_hint": "image_identity",
            "topic_hint": "sunscreen",
            "continuity_hint": "new_task",
            "subject_scope_hint": "self",
            "reference_mentions": [],
            "product_mentions": [],
            "budget_candidates": [],
            "observation_candidates": [],
            "preference_candidates": [],
            "relative_candidates": [],
            "consultation_hypothesis": None,
            "next_observation_gap": None,
            "question_meaning": "确认图片中的防晒商品身份",
            "safety_language": "ordinary",
        },
        strict=True,
    )
    runtime = build_local_continuous_runtime(
        trajectory,
        tmp_path / "image-state",
        repo_root=Path.cwd(),
    )

    trace = execute_continuous_trajectory(
        trajectory,
        runtime=runtime,
        meanings=tuple(meanings),
    )

    first = trace.turns[0]
    assert first.route.processor == "image_identity"
    assert [binding.product_id for binding in first.bindings] == [53]
    assert first.card_ids == (53,)
    assert first.presentation_mode == "image_identity"
    assert first.final_snapshot.image_slot is not None


def test_multi_image_runtime_reports_the_actual_public_route(
    tmp_path: Path,
) -> None:
    trajectory = next(
        item
        for item in load_frozen_trajectories()
        if item.trajectory_id == "image-clarify-and-recover"
    )
    capture = json.loads(
        Path(
            "docs/audits/continuous-conversation/"
            "backend-20x5-real-v1.json"
        ).read_text(encoding="utf-8")
    )
    captured = next(
        row
        for row in capture["results"]
        if row["turn_id"] == "image-clarify-and-recover-t1"
    )
    meaning = TurnMeaning.model_validate(
        captured["provider_output"],
        strict=True,
    )
    runtime = build_local_continuous_runtime(
        trajectory,
        tmp_path / "multi-image-route-state",
        repo_root=Path.cwd(),
    )

    result = runtime.execute(
        session_id=trajectory.trajectory_id,
        conversation_version=0,
        message=trajectory.turns[0].message,
        meaning=meaning,
        image_fixture_ids=trajectory.turns[0].image_fixture_ids,
    )
    public_intent = next(
        data["intent"]
        for event, data in result.events
        if event == "intent"
    )
    public_processor = {
        "comparison": "comparison",
        "image_identity": "image_identity",
    }[public_intent]
    product_ids = tuple(
        item["id"]
        for event, data in result.events
        if event == "products"
        for item in data["products"]
    )
    presentation_mode = next(
        data["mode"]
        for event, data in result.events
        if event == "presentation_contract"
    )

    assert result.route.processor == public_processor
    assert result.route.processor == "image_identity"
    assert product_ids == (53, 55)
    assert presentation_mode == "image_identity"

    snapshot = runtime.load_snapshot(trajectory.trajectory_id)
    assert snapshot.active_owner.value == "image_identity"
    assert snapshot.active_focus is not None
    assert snapshot.active_focus.slot == "image"
    assert snapshot.active_focus.object_id is None
    assert snapshot.image_slot is not None
    assert [
        item.product_id
        for item in snapshot.image_slot.confirmed_products
    ] == [53, 55]
