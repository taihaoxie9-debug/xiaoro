from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.guide.retrieval.product_name_resolver import (
    ResolvedProductBinding,
)
from tools.guide_gates.continuous_conversation_fixture import (
    DEFAULT_POOL_PATH,
    freeze_continuous_fixtures,
)
from tools.guide_gates.continuous_conversation_gate import (
    ContinuousTrajectory,
    ContinuousTurnExpectation,
)
from tools.guide_gates.unified_router_gate import (
    RouteExpectation,
    SemanticExpectation,
)


@dataclass(frozen=True)
class _TurnDraft:
    message: str
    operations: tuple[str, ...]
    topics: tuple[str | None, ...]
    meaning_continuities: tuple[str, ...]
    subjects: tuple[str, ...]
    processor: str
    route_continuity: str
    focus_source: str
    policy: str
    presentation: str | None
    bindings: tuple[ResolvedProductBinding, ...] = ()
    cards: tuple[int, ...] = ()
    snapshot: dict[str, Any] | None = None
    task: dict[str, Any] | None = None
    image_fixture_ids: tuple[str, ...] = ()
    safety: bool = False
    clarification: bool = False


def _binding(
    product_id: int,
    source_text: str,
) -> ResolvedProductBinding:
    return ResolvedProductBinding(
        product_id=product_id,
        variant_scope=None,
        source_text=source_text,
    )


def _draft(
    message: str,
    *,
    operations: tuple[str, ...],
    topics: tuple[str | None, ...],
    meaning_continuities: tuple[str, ...],
    processor: str,
    route_continuity: str,
    focus_source: str,
    policy: str,
    presentation: str | None,
    subjects: tuple[str, ...] = ("self", "unknown"),
    bindings: tuple[ResolvedProductBinding, ...] = (),
    cards: tuple[int, ...] = (),
    snapshot: dict[str, Any] | None = None,
    task: dict[str, Any] | None = None,
    image_fixture_ids: tuple[str, ...] = (),
    safety: bool = False,
    clarification: bool = False,
) -> _TurnDraft:
    return _TurnDraft(
        message=message,
        operations=operations,
        topics=topics,
        meaning_continuities=meaning_continuities,
        subjects=subjects,
        processor=processor,
        route_continuity=route_continuity,
        focus_source=focus_source,
        policy=policy,
        presentation=presentation,
        bindings=bindings,
        cards=cards,
        snapshot=snapshot,
        task=task,
        image_fixture_ids=image_fixture_ids,
        safety=safety,
        clarification=clarification,
    )


def _recommend(
    message: str,
    *,
    topic: str = "serum",
    cards: tuple[int, ...] = (38, 91),
    route_continuity: str = "replace_task",
    meaning_continuities: tuple[str, ...] = ("new_task", "unknown"),
    presentation: str = "recommendation",
    subjects: tuple[str, ...] = ("self", "unknown"),
) -> _TurnDraft:
    return _draft(
        message,
        operations=("recommendation", "followup"),
        topics=(topic,),
        meaning_continuities=meaning_continuities,
        processor="recommendation",
        route_continuity=route_continuity,
        focus_source="none",
        policy="recommendation",
        presentation=presentation,
        subjects=subjects,
        cards=cards,
        task={"mode": "recommend"},
    )


def _product(
    message: str,
    *,
    product_id: int,
    source_text: str,
    topic: str = "serum",
    route_continuity: str = "continue",
    meaning_continuities: tuple[str, ...] = ("continue",),
    focus_source: str = "current_product",
    operations: tuple[str, ...] = ("knowledge", "followup"),
    task_mode: str = "knowledge",
    presentation: str = "product_knowledge",
    subjects: tuple[str, ...] = ("self", "unknown"),
) -> _TurnDraft:
    return _draft(
        message,
        operations=operations,
        topics=(topic, None),
        meaning_continuities=meaning_continuities,
        processor="product_knowledge",
        route_continuity=route_continuity,
        focus_source=focus_source,
        policy="product_knowledge",
        presentation=presentation,
        subjects=subjects,
        bindings=(_binding(product_id, source_text),),
        cards=(product_id,),
        snapshot={
            "focus_state": {
                "active_processor": "product_knowledge",
                "current_product_id": product_id,
            }
        },
        task={
            "mode": task_mode,
            "product_ids": [product_id],
        },
    )


def _knowledge(
    message: str,
    *,
    topic: str,
    route_continuity: str = "replace_task",
    meaning_continuities: tuple[str, ...] = ("new_task", "unknown"),
    subjects: tuple[str, ...] = ("self", "unknown"),
) -> _TurnDraft:
    return _draft(
        message,
        operations=("knowledge",),
        topics=(topic, None),
        meaning_continuities=meaning_continuities,
        processor="general_knowledge",
        route_continuity=route_continuity,
        focus_source="knowledge_topic",
        policy="general_knowledge",
        presentation="general_knowledge",
        subjects=subjects,
        snapshot={
            "focus_state": {
                "active_processor": "general_knowledge",
            }
        },
        task={},
    )


def _compare(
    message: str,
    *,
    products: tuple[tuple[int, str], ...],
    topic: str = "serum",
    route_continuity: str = "replace_task",
    meaning_continuities: tuple[str, ...] = ("new_task", "unknown"),
    subjects: tuple[str, ...] = ("self", "unknown"),
    presentation: str = "comparison",
) -> _TurnDraft:
    return _draft(
        message,
        operations=("comparison",),
        topics=(topic,),
        meaning_continuities=meaning_continuities,
        processor="comparison",
        route_continuity=route_continuity,
        focus_source="explicit_product",
        policy="comparison",
        presentation=presentation,
        subjects=subjects,
        bindings=tuple(
            _binding(product_id, source_text)
            for product_id, source_text in products
        ),
        cards=tuple(product_id for product_id, _ in products),
        snapshot={
            "focus_state": {
                "active_processor": "comparison",
            }
        },
        task={
            "mode": "comparison",
            "product_ids": [
                product_id for product_id, _ in products
            ],
        },
    )


def _consult(
    message: str,
    *,
    route_continuity: str = "continue",
    meaning_continuities: tuple[str, ...] = ("continue", "unknown"),
    subjects: tuple[str, ...] = ("self", "unknown"),
) -> _TurnDraft:
    return _draft(
        message,
        operations=("assessment", "followup"),
        topics=("skincare", None),
        meaning_continuities=meaning_continuities,
        processor="consultation",
        route_continuity=route_continuity,
        focus_source="consultation",
        policy="consultation",
        presentation="consultation",
        subjects=subjects,
        snapshot={
            "focus_state": {
                "active_processor": "consultation",
            }
        },
        task={},
    )


def _safety(
    message: str,
    *,
    subjects: tuple[str, ...] = ("self", "unknown"),
) -> _TurnDraft:
    return _draft(
        message,
        operations=("assessment",),
        topics=("skincare", None),
        meaning_continuities=("continue", "new_task", "unknown"),
        processor="safety_escalation",
        route_continuity="replace_task",
        focus_source="consultation",
        policy="safety",
        presentation="consultation",
        subjects=subjects,
        snapshot={
            "focus_state": {
                "active_processor": "safety_escalation",
            }
        },
        task={},
        safety=True,
    )


def _clarify(
    message: str,
    *,
    topic: str | None = None,
    subjects: tuple[str, ...] = ("self", "unknown"),
    clarification_gap: str = "goal",
    resume_processor: str | None = None,
) -> _TurnDraft:
    snapshot: dict[str, Any] = {
        "clarification": {
            "gap": clarification_gap,
            "attempts": 1,
        },
    }
    if resume_processor is not None:
        snapshot["focus_state"] = {
            "active_processor": resume_processor,
        }
    return _draft(
        message,
        operations=("clarification", "knowledge", "recommendation"),
        topics=(topic, None) if topic is not None else (None,),
        meaning_continuities=("new_task", "continue", "unknown"),
        processor="clarification",
        route_continuity="replace_task",
        focus_source="none",
        policy="clarification",
        presentation=None,
        subjects=subjects,
        snapshot=snapshot,
        task={"mode": "clarify"},
        clarification=True,
    )


def _image_identity(
    message: str,
    *,
    fixtures: tuple[str, ...],
    products: tuple[int, ...],
    topic: str = "sunscreen",
    presentation: str = "product_knowledge",
) -> _TurnDraft:
    return _draft(
        message,
        operations=(
            "image_identity",
            "knowledge",
            "followup",
            "image_similarity",
        ),
        topics=(topic, None),
        meaning_continuities=("new_task", "unknown"),
        processor="image_identity",
        route_continuity="replace_task",
        focus_source="confirmed_image",
        policy="product_knowledge",
        presentation=presentation,
        bindings=tuple(
            _binding(product_id, f"image_ordinal:{ordinal}")
            for ordinal, product_id in enumerate(products, start=1)
        ),
        cards=products,
        snapshot={
            "has_image_delivery": True,
            "focus_state": {
                "active_processor": "image_identity",
                "current_product_id": products[0],
                "confirmed_image_products": [
                    {
                        "image_ordinal": ordinal,
                        "product_id": product_id,
                        "variant_scope": None,
                    }
                    for ordinal, product_id in enumerate(
                        products,
                        start=1,
                    )
                ],
            },
        },
        task={},
        image_fixture_ids=fixtures,
    )


def _image_suitability(
    message: str,
    *,
    product_id: int,
    ordinal: int = 1,
) -> _TurnDraft:
    return _product(
        message,
        product_id=product_id,
        source_text=f"image_ordinal:{ordinal}",
        topic="sunscreen",
        focus_source="confirmed_image",
        operations=("suitability", "assessment"),
        task_mode="suitability",
        presentation="product_knowledge",
    )


def _image_similarity(
    message: str,
    *,
    cards: tuple[int, ...],
    topic: str = "sunscreen",
) -> _TurnDraft:
    return _draft(
        message,
        operations=("image_similarity",),
        topics=(topic, None),
        meaning_continuities=("continue", "unknown"),
        processor="recommendation",
        route_continuity="continue",
        focus_source="confirmed_image",
        policy="recommendation",
        presentation="image_recommendation",
        cards=cards,
        snapshot={
            "focus_state": {
                "active_processor": "recommendation",
            }
        },
        task={"mode": "recommend"},
    )


def _trajectory(
    trajectory_id: str,
    *,
    scope: str,
    families: tuple[str, ...],
    turns: tuple[_TurnDraft, ...],
) -> ContinuousTrajectory:
    if len(turns) != 5:
        raise ValueError("trajectory blueprint requires five turns")
    return ContinuousTrajectory(
        trajectory_id=trajectory_id,
        subject_scope=scope,
        route_families=families,
        turns=tuple(
            ContinuousTurnExpectation(
                turn_id=f"{trajectory_id}-t{index}",
                message=draft.message,
                image_fixture_ids=draft.image_fixture_ids,
                acceptable_semantic=SemanticExpectation(
                    operation_hints=draft.operations,
                    topic_hints=draft.topics,
                    continuity_hints=draft.meaning_continuities,
                    subject_scope_hints=draft.subjects,
                ),
                expected_bindings=draft.bindings,
                expected_route=RouteExpectation(
                    processor=draft.processor,
                    continuity=draft.route_continuity,
                    focus_source=draft.focus_source,
                ),
                expected_snapshot_subset=(
                    draft.snapshot
                    if draft.snapshot is not None
                    else {
                        "focus_state": {
                            "active_processor": draft.processor,
                        }
                    }
                ),
                expected_task_plan_subset=(
                    draft.task if draft.task is not None else {}
                ),
                expected_card_ids=draft.cards,
                expected_safety=draft.safety,
                expected_clarification=draft.clarification,
                expected_presentation_mode=draft.presentation,
                public_answer_policy=draft.policy,
            )
            for index, draft in enumerate(turns, start=1)
        ),
    )


def build_reviewed_trajectory_pool() -> tuple[
    ContinuousTrajectory,
    ...,
]:
    trajectories = (
        _trajectory(
            "shop-repair-budget-return",
            scope="self",
            families=(
                "recommendation_revision",
                "product_followup",
                "general_knowledge_return",
            ),
            turns=(
                _recommend("敏感肌想找五百以内的修护精华，别太厚重"),
                _product(
                    "先展开第二款，我更关心它早晚怎么用",
                    product_id=91,
                    source_text="candidate_ordinal:2",
                    focus_source="candidate_batch",
                    task_mode="followup",
                ),
                _knowledge(
                    "顺便问一句，烟酰胺和视黄醇是不是同一种成分",
                    topic="serum",
                ),
                _product(
                    "知识先放一边，回到刚才第二款，它适合我现在泛红时用吗",
                    product_id=91,
                    source_text="current_product",
                    route_continuity="return_to_focus",
                    meaning_continuities=("return_to_focus",),
                    operations=("suitability", "followup"),
                    task_mode="suitability",
                ),
                _recommend(
                    "原来的修护方向保留，预算改成一百元封顶",
                    cards=(91,),
                    route_continuity="correct",
                    meaning_continuities=("continue",),
                    presentation="revision",
                ),
            ),
        ),
        _trajectory(
            "shop-exclusion-withdrawal",
            scope="self",
            families=(
                "recommendation_revision",
                "product_followup",
            ),
            turns=(
                _recommend("给我挑修护精华，敏感皮，先排除酒精"),
                _recommend(
                    "价格再压到三百以内，其他条件别动",
                    route_continuity="correct",
                    meaning_continuities=("continue",),
                    presentation="revision",
                ),
                _product(
                    "第一款的质地和使用顺序具体怎样",
                    product_id=38,
                    source_text="candidate_ordinal:1",
                    focus_source="candidate_batch",
                    task_mode="followup",
                ),
                _compare(
                    "把理肤泉B5精华和修丽可CE精华横向比一下",
                    products=((38, "理肤泉B5精华"), (34, "修丽可CE精华")),
                ),
                _recommend(
                    "酒精排除取消，回到三百以内的修护精华",
                    route_continuity="withdraw",
                    meaning_continuities=("continue",),
                ),
            ),
        ),
        _trajectory(
            "shop-product-to-alternatives",
            scope="self",
            families=(
                "product_followup",
                "recommendation_revision",
                "comparison",
            ),
            turns=(
                _product(
                    "理肤泉新B5多效修护精华的质地和用法怎么样",
                    product_id=38,
                    source_text="理肤泉新B5多效修护精华",
                    route_continuity="replace_task",
                    meaning_continuities=("new_task", "unknown"),
                    focus_source="explicit_product",
                ),
                _product(
                    "我最近擦东西偶尔刺痛，它现在适合我吗",
                    product_id=38,
                    source_text="current_product",
                    operations=("suitability", "assessment"),
                    task_mode="suitability",
                ),
                _recommend(
                    "那换成更稳妥的修护精华，预算还是五百",
                ),
                _recommend(
                    "预算提到八百，但敏感和修护方向不变",
                    route_continuity="correct",
                    meaning_continuities=("continue",),
                    presentation="revision",
                ),
                _compare(
                    "最后只比B5精华和玉泽屏障修护精华",
                    products=((38, "B5精华"), (91, "玉泽屏障修护精华")),
                ),
            ),
        ),
        _trajectory(
            "shop-comparison-course-change",
            scope="self",
            families=(
                "comparison",
                "recommendation_revision",
                "general_knowledge_return",
            ),
            turns=(
                _compare(
                    "修丽可CE精华和理肤泉B5精华的路线差在哪",
                    products=((34, "修丽可CE精华"), (38, "理肤泉B5精华")),
                ),
                _recommend(
                    "这两个都先放下，给敏感皮换一组五百内的修护精华",
                ),
                _recommend(
                    "再加一条，我希望上脸清爽一些",
                    route_continuity="supplement",
                    meaning_continuities=("continue",),
                    presentation="revision",
                ),
                _knowledge(
                    "玻色因主要解决什么问题",
                    topic="serum",
                ),
                _product(
                    "回到刚才推荐里的第一款，说说品牌主打和用法",
                    product_id=38,
                    source_text="candidate_ordinal:1",
                    route_continuity="return_to_focus",
                    meaning_continuities=("return_to_focus",),
                    focus_source="candidate_batch",
                    task_mode="followup",
                ),
            ),
        ),
        _trajectory(
            "shop-sunscreen-commute",
            scope="self",
            families=(
                "recommendation_revision",
                "product_followup",
                "general_knowledge_return",
                "comparison",
            ),
            turns=(
                _recommend(
                    "通勤用的清爽防晒，三百以内给我看两款",
                    topic="sunscreen",
                    cards=(53, 55),
                ),
                _product(
                    "第一款会不会熏眼，规格和用量也讲一下",
                    product_id=53,
                    source_text="candidate_ordinal:1",
                    topic="sunscreen",
                    focus_source="candidate_batch",
                    task_mode="followup",
                ),
                _knowledge(
                    "SPF和PA这两个指标分别管什么",
                    topic="sunscreen",
                ),
                _product(
                    "回到之前那支防晒，敏感泛红时能不能继续用",
                    product_id=53,
                    source_text="current_product",
                    topic="sunscreen",
                    route_continuity="return_to_focus",
                    meaning_continuities=("return_to_focus",),
                    operations=("suitability", "assessment"),
                    task_mode="suitability",
                ),
                _compare(
                    "把它和清透防晒乳按肤感、价格、规格比较",
                    products=((53, "它"), (55, "清透防晒乳")),
                    topic="sunscreen",
                ),
            ),
        ),
        _trajectory(
            "shop-vague-to-sunscreen",
            scope="self",
            families=(
                "clarification_recovery",
                "recommendation_revision",
                "comparison",
            ),
            turns=(
                _clarify("想要一个清爽点的，别太贵", topic=None),
                _recommend(
                    "我说的是防晒，预算两百，日常通勤",
                    topic="sunscreen",
                    cards=(53, 55),
                    meaning_continuities=("continue", "new_task"),
                ),
                _recommend(
                    "使用场景改成周末户外，预算不变",
                    topic="sunscreen",
                    cards=(53, 55),
                    route_continuity="correct",
                    meaning_continuities=("continue",),
                    presentation="revision",
                ),
                _compare(
                    "这两支防晒就按防护和肤感比较",
                    products=((53, "第一支防晒"), (55, "第二支防晒")),
                    topic="sunscreen",
                ),
                _product(
                    "我倾向第一支，再把它的用法说明白",
                    product_id=53,
                    source_text="candidate_ordinal:1",
                    topic="sunscreen",
                    focus_source="candidate_batch",
                    task_mode="followup",
                ),
            ),
        ),
        _trajectory(
            "shop-condition-reset",
            scope="self",
            families=(
                "recommendation_revision",
                "product_followup",
                "general_knowledge_return",
            ),
            turns=(
                _recommend("四百以内找抗老精华，我偏干还容易泛红"),
                _recommend(
                    "抗老先撤掉，改成保湿修护优先",
                    route_continuity="correct",
                    meaning_continuities=("continue",),
                    presentation="revision",
                ),
                _product(
                    "第二款为什么排进来，现有资料能确认哪些点",
                    product_id=91,
                    source_text="candidate_ordinal:2",
                    focus_source="candidate_batch",
                    task_mode="followup",
                ),
                _knowledge(
                    "敏感肌和过敏是一回事吗",
                    topic="skincare",
                ),
                _product(
                    "回去继续第二款，只说质地、规格和用法",
                    product_id=91,
                    source_text="current_product",
                    route_continuity="return_to_focus",
                    meaning_continuities=("return_to_focus",),
                    task_mode="followup",
                ),
            ),
        ),
        _trajectory(
            "shop-three-product-narrowing",
            scope="self",
            families=(
                "comparison",
                "recommendation_revision",
                "product_followup",
            ),
            turns=(
                _compare(
                    "B5精华、玉泽屏障修护精华和CE精华三款一起比",
                    products=(
                        (38, "B5精华"),
                        (91, "玉泽屏障修护精华"),
                        (34, "CE精华"),
                    ),
                ),
                _product(
                    "第三款先单独展开，适合人群和使用顺序是什么",
                    product_id=34,
                    source_text="candidate_ordinal:3",
                    focus_source="candidate_batch",
                    task_mode="followup",
                ),
                _recommend(
                    "价格太高，回到五百以内重新给两款",
                    route_continuity="correct",
                    meaning_continuities=("continue",),
                    presentation="revision",
                ),
                _compare(
                    "新结果里只保留前两款做最后比较",
                    products=((38, "第一款"), (91, "第二款")),
                    route_continuity="continue",
                    meaning_continuities=("continue",),
                ),
                _product(
                    "我选第一款，告诉我日常怎么搭配",
                    product_id=38,
                    source_text="candidate_ordinal:1",
                    focus_source="candidate_batch",
                    task_mode="followup",
                ),
            ),
        ),
        _trajectory(
            "knowledge-live-probe",
            scope="self",
            families=(
                "recommendation_revision",
                "product_followup",
                "general_knowledge_return",
            ),
            turns=(
                _recommend("敏感肌修护精华，预算五百以内"),
                _product(
                    "第二款质地和用法怎么样",
                    product_id=91,
                    source_text="candidate_ordinal:2",
                    focus_source="candidate_batch",
                    task_mode="followup",
                ),
                _knowledge(
                    "烟酰胺跟视黄醇到底是不是一回事",
                    topic="serum",
                ),
                _product(
                    "回到前面第二款，它适合我现在的状态吗",
                    product_id=91,
                    source_text="current_product",
                    route_continuity="return_to_focus",
                    meaning_continuities=("return_to_focus",),
                    operations=("suitability", "followup"),
                    task_mode="suitability",
                ),
                _recommend(
                    "把最开始的预算降到一百，重新推荐",
                    cards=(91,),
                    route_continuity="correct",
                    meaning_continuities=("continue",),
                    presentation="revision",
                ),
            ),
        ),
        _trajectory(
            "knowledge-product-detour",
            scope="self",
            families=(
                "product_followup",
                "general_knowledge_return",
                "comparison",
            ),
            turns=(
                _product(
                    "B5精华平时放在哪一步，用量怎么把握",
                    product_id=38,
                    source_text="B5精华",
                    route_continuity="replace_task",
                    meaning_continuities=("new_task",),
                    focus_source="explicit_product",
                ),
                _knowledge(
                    "烟酰胺为什么能帮助修护屏障",
                    topic="serum",
                ),
                _product(
                    "回到B5那瓶，它页面里的品牌主打有哪些",
                    product_id=38,
                    source_text="current_product",
                    route_continuity="return_to_focus",
                    meaning_continuities=("return_to_focus",),
                    task_mode="followup",
                ),
                _compare(
                    "再把B5精华和CE精华放一起看差异",
                    products=((38, "B5精华"), (34, "CE精华")),
                ),
                _product(
                    "只继续CE精华，告诉我规格和注意事项",
                    product_id=34,
                    source_text="CE精华",
                    focus_source="explicit_product",
                    task_mode="followup",
                ),
            ),
        ),
        _trajectory(
            "knowledge-sunscreen-loop",
            scope="self",
            families=(
                "general_knowledge_return",
                "recommendation_revision",
                "product_followup",
            ),
            turns=(
                _knowledge(
                    "为什么阴天也有人建议涂防晒",
                    topic="sunscreen",
                ),
                _recommend(
                    "按通勤清爽这个方向给我两支两百内的防晒",
                    topic="sunscreen",
                    cards=(53, 55),
                ),
                _product(
                    "第二支包装上能确认什么规格",
                    product_id=55,
                    source_text="candidate_ordinal:2",
                    topic="sunscreen",
                    focus_source="candidate_batch",
                    task_mode="followup",
                ),
                _knowledge(
                    "防晒补涂主要受哪些场景影响",
                    topic="sunscreen",
                ),
                _product(
                    "回到第二支，它在户外场景的资料够不够",
                    product_id=55,
                    source_text="current_product",
                    topic="sunscreen",
                    route_continuity="return_to_focus",
                    meaning_continuities=("return_to_focus",),
                    task_mode="followup",
                ),
            ),
        ),
        _trajectory(
            "knowledge-ingredient-to-product",
            scope="self",
            families=(
                "general_knowledge_return",
                "product_followup",
                "comparison",
            ),
            turns=(
                _knowledge(
                    "玻色因和肽类在抗老方向上有什么区别",
                    topic="serum",
                ),
                _product(
                    "理肤泉B5精华有没有这些成分信息",
                    product_id=38,
                    source_text="理肤泉B5精华",
                    route_continuity="replace_task",
                    meaning_continuities=("new_task",),
                    focus_source="explicit_product",
                ),
                _product(
                    "先不谈适合不适合，只讲它的用法",
                    product_id=38,
                    source_text="current_product",
                    task_mode="followup",
                ),
                _knowledge(
                    "A醇建立耐受一般要注意哪些事",
                    topic="skincare",
                ),
                _product(
                    "返回刚才B5精华，敏感时该怎么试用",
                    product_id=38,
                    source_text="current_product",
                    route_continuity="return_to_focus",
                    meaning_continuities=("return_to_focus",),
                    operations=("suitability", "followup"),
                    task_mode="suitability",
                ),
            ),
        ),
        _trajectory(
            "knowledge-consultation-switch",
            scope="self",
            families=(
                "consultation_profile",
                "general_knowledge_return",
                "recommendation_revision",
            ),
            turns=(
                _consult(
                    "我分不清自己什么肤质，洗完脸会紧但下午鼻子油",
                    route_continuity="replace_task",
                    meaning_continuities=("new_task",),
                ),
                _consult("换季还会红，偶尔擦护肤品有点刺"),
                _knowledge(
                    "敏感倾向和皮肤过敏怎么区分",
                    topic="skincare",
                ),
                _consult(
                    "先回到刚才问诊，我补充一下两颊更容易干",
                    route_continuity="return_to_focus",
                    meaning_continuities=("return_to_focus",),
                ),
                _recommend(
                    "按刚才暂定状态给我找三百内修护精华",
                ),
            ),
        ),
        _trajectory(
            "consult-mixed-dehydration",
            scope="self",
            families=("consultation_profile",),
            turns=(
                _consult(
                    "脸有时冒油有时发干，我不知道算哪种肤质",
                    route_continuity="replace_task",
                    meaning_continuities=("new_task",),
                ),
                _consult("主要是T区油，两边洗完会绷"),
                _consult("换季会轻微泛红，但平时不怎么刺痛"),
                _consult("补充一下，夏天整体又会比现在油"),
                _recommend("根据这些情况看三百内的清爽修护精华"),
            ),
        ),
        _trajectory(
            "consult-safety-pivot",
            scope="self",
            families=(
                "consultation_profile",
                "safety_escalation",
            ),
            turns=(
                _consult(
                    "最近护肤后会发热泛红，想看看是什么状态",
                    route_continuity="replace_task",
                    meaning_continuities=("new_task",),
                ),
                _consult("通常十几分钟缓下来，没有破皮"),
                _safety("今天突然有一块破了还在往外渗液"),
                _safety("现在仍然在渗，而且碰水会疼"),
                _knowledge(
                    "先不选产品，告诉我什么情况需要尽快就医",
                    topic="skincare",
                ),
            ),
        ),
        _trajectory(
            "consult-correction",
            scope="self",
            families=("consultation_profile",),
            turns=(
                _consult(
                    "我好像是油皮，但冬天洗脸后也紧",
                    route_continuity="replace_task",
                    meaning_continuities=("new_task",),
                ),
                _consult("额头和鼻子出油明显，两颊通常正常"),
                _consult("刚才说错了，两颊其实经常起皮"),
                _consult("没有刺痛，也没有持续泛红"),
                _recommend("先按修护和保湿优先，预算二百"),
            ),
        ),
        _trajectory(
            "consult-product-interruption",
            scope="self",
            families=(
                "consultation_profile",
                "product_followup",
                "general_knowledge_return",
            ),
            turns=(
                _consult(
                    "不知道肤质，只知道下午会油，空调房又干",
                    route_continuity="replace_task",
                    meaning_continuities=("new_task",),
                ),
                _consult("油主要在鼻子，脸颊干但不红"),
                _product(
                    "先插一句，B5精华这种状态能用吗",
                    product_id=38,
                    source_text="B5精华",
                    route_continuity="replace_task",
                    meaning_continuities=("new_task",),
                    focus_source="explicit_product",
                    operations=("suitability",),
                    task_mode="suitability",
                ),
                _consult(
                    "商品先放下，回到肤质判断，我偶尔还会闷痘",
                    route_continuity="return_to_focus",
                    meaning_continuities=("return_to_focus",),
                ),
                _recommend("按目前观察给我选轻薄修护精华"),
            ),
        ),
        _trajectory(
            "consult-friend-boundary",
            scope="mixed",
            families=(
                "consultation_profile",
                "other_person_isolation",
            ),
            turns=(
                _consult(
                    "我替室友问，她脸颊干，鼻子油，换季会红",
                    route_continuity="replace_task",
                    meaning_continuities=("new_task",),
                    subjects=("other",),
                ),
                _consult(
                    "她没有刺痛，主要是洗完脸紧",
                    subjects=("other",),
                ),
                _recommend(
                    "按她的情况找两百以内修护精华",
                    subjects=("other",),
                ),
                _consult(
                    "现在换成问我自己，我是全脸偏油也不泛红",
                    route_continuity="replace_task",
                    meaning_continuities=("new_task",),
                    subjects=("self",),
                ),
                _recommend(
                    "给我本人看清爽精华，别沿用她的干敏条件",
                    subjects=("self",),
                ),
            ),
        ),
        _trajectory(
            "image-sunscreen-suitability",
            scope="self",
            families=(
                "image_identity",
                "image_similarity",
                "comparison",
            ),
            turns=(
                _image_identity(
                    "帮我看图里这支防晒是什么",
                    fixtures=("product-53-front",),
                    products=(53,),
                ),
                _image_suitability(
                    "这支对敏感肌来说可以先作为候选吗",
                    product_id=53,
                ),
                _product(
                    "我最近刚好泛红刺痛，结论需要怎么调整",
                    product_id=53,
                    source_text="image_ordinal:1",
                    topic="sunscreen",
                    focus_source="confirmed_image",
                    operations=("suitability", "assessment"),
                    task_mode="suitability",
                    presentation="image_suitability",
                ),
                _image_similarity(
                    "按它的清爽防晒方向找两款相似的",
                    cards=(53, 55),
                ),
                _compare(
                    "把相似结果里的两支横向比较",
                    products=((53, "第一支"), (55, "第二支")),
                    topic="sunscreen",
                    route_continuity="continue",
                    meaning_continuities=("continue",),
                    presentation="image_comparison",
                ),
            ),
        ),
        _trajectory(
            "image-two-product-comparison",
            scope="self",
            families=(
                "image_identity",
                "comparison",
                "general_knowledge_return",
            ),
            turns=(
                _image_identity(
                    "这两张图分别是什么，先别急着选",
                    fixtures=("product-53-front", "product-55-front"),
                    products=(53, 55),
                    presentation="comparison",
                ),
                _compare(
                    "按防护、肤感和价格比较两张图里的商品",
                    products=(
                        (53, "image_ordinal:1"),
                        (55, "image_ordinal:2"),
                    ),
                    topic="sunscreen",
                    route_continuity="continue",
                    meaning_continuities=("continue",),
                    presentation="comparison",
                ),
                _product(
                    "第一张那支单独讲一下用量和规格",
                    product_id=53,
                    source_text="image_ordinal:1",
                    topic="sunscreen",
                    focus_source="confirmed_image",
                    task_mode="followup",
                    presentation="product_knowledge",
                ),
                _knowledge(
                    "户外防晒为什么更需要补涂",
                    topic="sunscreen",
                ),
                _product(
                    "回到第一张商品，品牌主打还有哪些",
                    product_id=53,
                    source_text="current_product",
                    topic="sunscreen",
                    route_continuity="return_to_focus",
                    meaning_continuities=("return_to_focus",),
                    task_mode="followup",
                    presentation="product_knowledge",
                ),
            ),
        ),
        _trajectory(
            "image-budget-similarity",
            scope="self",
            families=(
                "image_identity",
                "image_similarity",
                "recommendation_revision",
            ),
            turns=(
                _image_identity(
                    "识别一下照片里的清透防晒乳",
                    fixtures=("product-55-front",),
                    products=(55,),
                ),
                _product(
                    "它的参考价后面为什么没有规格，帮我核对",
                    product_id=55,
                    source_text="image_ordinal:1",
                    topic="sunscreen",
                    focus_source="confirmed_image",
                    task_mode="followup",
                    presentation="product_knowledge",
                ),
                _image_similarity(
                    "找相似方向，但预算必须在一百以内",
                    cards=(55,),
                ),
                _recommend(
                    "预算放到一百五，仍然要清爽通勤",
                    topic="sunscreen",
                    cards=(53, 55),
                    route_continuity="correct",
                    meaning_continuities=("continue",),
                    presentation="revision",
                ),
                _product(
                    "新结果里第二款适用肤质怎么写的",
                    product_id=55,
                    source_text="candidate_ordinal:2",
                    topic="sunscreen",
                    focus_source="candidate_batch",
                    task_mode="followup",
                ),
            ),
        ),
        _trajectory(
            "image-clarify-and-recover",
            scope="self",
            families=(
                "image_identity",
                "clarification_recovery",
                "image_similarity",
            ),
            turns=(
                _image_identity(
                    "我上传两张，先确认各自是什么",
                    fixtures=("product-53-front", "product-55-front"),
                    products=(53, 55),
                    presentation="comparison",
                ),
                _clarify("看那张图，帮我继续判断", topic="sunscreen"),
                _image_suitability(
                    "我说第一张，它适合敏感倾向吗",
                    product_id=53,
                    ordinal=1,
                ),
                _image_similarity(
                    "改看第二张，照它找一百元内的相似款",
                    cards=(55,),
                ),
                _product(
                    "相似结果先不扩展，只讲第二张原商品的用法",
                    product_id=55,
                    source_text="image_ordinal:2",
                    topic="sunscreen",
                    focus_source="confirmed_image",
                    task_mode="followup",
                    presentation="product_knowledge",
                ),
            ),
        ),
        _trajectory(
            "image-consultation-return",
            scope="self",
            families=(
                "image_identity",
                "consultation_profile",
                "general_knowledge_return",
            ),
            turns=(
                _image_identity(
                    "看看图中防晒是什么，资料里主打什么",
                    fixtures=("product-53-front",),
                    products=(53,),
                ),
                _consult(
                    "先不判断它，我脸现在又红又刺，想确认状态",
                    route_continuity="replace_task",
                    meaning_continuities=("new_task",),
                ),
                _consult("没有破皮，只是涂东西会疼"),
                _product(
                    "回到图片那支，结合现在状态还能不能试",
                    product_id=53,
                    source_text="image_ordinal:1",
                    topic="sunscreen",
                    route_continuity="return_to_focus",
                    meaning_continuities=("return_to_focus",),
                    focus_source="confirmed_image",
                    operations=("suitability", "assessment"),
                    task_mode="suitability",
                    presentation="product_knowledge",
                ),
                _knowledge(
                    "敏感急性期一般为什么要减少叠加",
                    topic="skincare",
                ),
            ),
        ),
        _trajectory(
            "recovery-ambiguous-product",
            scope="self",
            families=(
                "clarification_recovery",
                "product_followup",
                "comparison",
            ),
            turns=(
                _clarify("B5这个到底怎么样", topic="serum"),
                _product(
                    "我指理肤泉新B5多效修护精华",
                    product_id=38,
                    source_text="理肤泉新B5多效修护精华",
                    route_continuity="supplement",
                    meaning_continuities=("continue",),
                    focus_source="explicit_product",
                ),
                _product(
                    "它每天几次，放在面霜前还是后",
                    product_id=38,
                    source_text="current_product",
                    task_mode="followup",
                ),
                _product(
                    "不是问面霜，我只问这瓶精华的步骤",
                    product_id=38,
                    source_text="current_product",
                    meaning_continuities=("continue",),
                    task_mode="followup",
                ),
                _compare(
                    "再和玉泽屏障修护精华比较",
                    products=((38, "这瓶精华"), (91, "玉泽屏障修护精华")),
                ),
            ),
        ),
        _trajectory(
            "recovery-pending-affirm",
            scope="self",
            families=(
                "pending_turn",
                "clarification_recovery",
                "recommendation_revision",
            ),
            turns=(
                _clarify("想看敏感肌修护精华，预算大概五百吧", topic="serum"),
                _recommend(
                    "对，五百就是上限",
                    meaning_continuities=("continue", "unknown"),
                ),
                _product(
                    "结果里第二款先讲清楚",
                    product_id=91,
                    source_text="candidate_ordinal:2",
                    focus_source="candidate_batch",
                    task_mode="followup",
                ),
                _recommend(
                    "再把预算降到两百",
                    route_continuity="correct",
                    meaning_continuities=("continue",),
                    presentation="revision",
                ),
                _product(
                    "新结果第一款的规格是什么",
                    product_id=91,
                    source_text="candidate_ordinal:1",
                    focus_source="candidate_batch",
                    task_mode="followup",
                ),
            ),
        ),
        _trajectory(
            "recovery-pending-correct",
            scope="self",
            families=(
                "pending_turn",
                "clarification_recovery",
                "recommendation_revision",
            ),
            turns=(
                _clarify("修护精华两三百左右都行", topic="serum"),
                _clarify("不是三百封顶，我还没决定具体上限", topic="serum"),
                _recommend(
                    "那就明确四百以内，敏感肌修护",
                    meaning_continuities=("continue",),
                ),
                _recommend(
                    "加上清爽偏好，不要改预算",
                    route_continuity="supplement",
                    meaning_continuities=("continue",),
                    presentation="revision",
                ),
                _product(
                    "第二款是否有明确的适用资料",
                    product_id=91,
                    source_text="candidate_ordinal:2",
                    focus_source="candidate_batch",
                    task_mode="followup",
                ),
            ),
        ),
        _trajectory(
            "recovery-safety-boundary",
            scope="self",
            families=(
                "safety_escalation",
                "clarification_recovery",
            ),
            turns=(
                _safety("脸上已经破皮渗水，还能继续涂精华吗"),
                _safety("渗出没有停，而且范围比刚才大"),
                _knowledge(
                    "这种情况先做哪些最基本的处理",
                    topic="skincare",
                ),
                _clarify("那还能不能用点东西", topic="skincare"),
                _safety("我指的是伤口还在渗的时候能不能涂护肤品"),
            ),
        ),
        _trajectory(
            "isolation-friend-sunscreen",
            scope="mixed",
            families=(
                "other_person_isolation",
                "recommendation_revision",
                "product_followup",
            ),
            turns=(
                _recommend(
                    "替朋友找油敏肌通勤防晒，预算两百",
                    topic="sunscreen",
                    cards=(53, 55),
                    subjects=("other",),
                ),
                _product(
                    "她想看第二款，重点讲肤感",
                    product_id=55,
                    source_text="candidate_ordinal:2",
                    topic="sunscreen",
                    focus_source="candidate_batch",
                    task_mode="followup",
                    subjects=("other",),
                ),
                _recommend(
                    "她预算改成一百以内",
                    topic="sunscreen",
                    cards=(55,),
                    route_continuity="correct",
                    meaning_continuities=("continue",),
                    presentation="revision",
                    subjects=("other",),
                ),
                _recommend(
                    "接下来问我本人，我是干皮，预算三百",
                    topic="sunscreen",
                    cards=(53, 55),
                    subjects=("self",),
                ),
                _product(
                    "我自己的结果里第一款怎么用",
                    product_id=53,
                    source_text="candidate_ordinal:1",
                    topic="sunscreen",
                    focus_source="candidate_batch",
                    task_mode="followup",
                    subjects=("self",),
                ),
            ),
        ),
        _trajectory(
            "isolation-sister-serum",
            scope="mixed",
            families=(
                "other_person_isolation",
                "general_knowledge_return",
                "comparison",
            ),
            turns=(
                _recommend(
                    "给我姐看修护精华，她干敏，五百以内",
                    subjects=("other",),
                ),
                _knowledge(
                    "她想知道烟酰胺和A醇能不能一起用",
                    topic="skincare",
                    subjects=("other",),
                ),
                _product(
                    "回到给她挑的第一款，说明使用顺序",
                    product_id=38,
                    source_text="candidate_ordinal:1",
                    route_continuity="return_to_focus",
                    meaning_continuities=("return_to_focus",),
                    focus_source="candidate_batch",
                    task_mode="followup",
                    subjects=("other",),
                ),
                _compare(
                    "给她把B5和玉泽两款放表里比",
                    products=((38, "B5"), (91, "玉泽")),
                    subjects=("other",),
                ),
                _knowledge(
                    "最后一个问题是我自己的：油皮为什么也会缺水",
                    topic="skincare",
                    subjects=("self",),
                ),
            ),
        ),
        _trajectory(
            "isolation-colleague-consult",
            scope="mixed",
            families=(
                "other_person_isolation",
                "consultation_profile",
                "recommendation_revision",
            ),
            turns=(
                _consult(
                    "同事让我帮问，她下午出油但洗完会紧",
                    route_continuity="replace_task",
                    meaning_continuities=("new_task",),
                    subjects=("other",),
                ),
                _consult(
                    "她换季不红，也从来不刺痛",
                    subjects=("other",),
                ),
                _recommend(
                    "按她的状态找两百内保湿精华",
                    subjects=("other",),
                ),
                _recommend(
                    "这轮切到我自己，我敏感泛红，预算五百",
                    subjects=("self",),
                ),
                _product(
                    "我本人结果的第二款适合什么肤质",
                    product_id=91,
                    source_text="candidate_ordinal:2",
                    focus_source="candidate_batch",
                    task_mode="followup",
                    subjects=("self",),
                ),
            ),
        ),
    )
    if len(trajectories) != 30:
        raise AssertionError("reviewed trajectory pool must contain 30")
    return trajectories


def write_reviewed_trajectory_pool(
    path: Path = DEFAULT_POOL_PATH,
) -> None:
    pool = build_reviewed_trajectory_pool()
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(
        b"\n".join(
            trajectory.model_dump_json().encode("utf-8")
            for trajectory in pool
        )
        + b"\n"
    )


def main() -> int:
    write_reviewed_trajectory_pool()
    freeze_continuous_fixtures()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "build_reviewed_trajectory_pool",
    "write_reviewed_trajectory_pool",
]
