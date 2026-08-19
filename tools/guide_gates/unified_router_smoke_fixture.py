from __future__ import annotations

from collections.abc import Sequence

from tools.guide_gates.run_real_unified_router_gate import (
    GateCategory,
    RealUnifiedRouterCase,
)
from tools.guide_gates.unified_router_gate import ReplayCase


_BASE_CATEGORIES: dict[str, GateCategory] = {
    "offline-recommend-serum-001": "recommendation",
    "offline-general-knowledge-001": "general_knowledge",
    "offline-consultation-multi-observation-001": "consultation",
    "offline-safety-active-damage-001": "safety",
    "offline-product-knowledge-b5-001": "product_knowledge",
    "offline-comparison-two-serums-001": "comparison",
    "offline-ambiguous-b5-clarification-001": "clarification",
    "offline-followup-second-product-001": "product_knowledge",
    "offline-budget-revision-001": "state_transition",
    "offline-return-product-focus-001": "state_transition",
    "offline-pending-affirmation-001": "state_transition",
    "offline-pending-rejection-001": "clarification",
    "offline-withdraw-exclusion-001": "state_transition",
    "offline-session-profile-projection-001": "recommendation",
    "offline-friend-profile-isolation-001": "recommendation",
    "offline-confirmed-image-suitability-001": "image",
}

_VARIANTS: tuple[tuple[str, str, str], ...] = (
    (
        "offline-recommend-serum-001",
        "smoke-rec-sensitive-repair-001",
        "敏感肌想看修护精华，预算别超过500",
    ),
    (
        "offline-recommend-serum-001",
        "smoke-rec-sensitive-repair-002",
        "五百封顶，给我挑敏感肌修护精华",
    ),
    (
        "offline-recommend-serum-001",
        "smoke-rec-sensitive-repair-003",
        "修护精华预算500以内，我皮肤比较敏感",
    ),
    (
        "offline-general-knowledge-001",
        "smoke-knowledge-reapply-001",
        "防晒在外面待久了为啥还得补",
    ),
    (
        "offline-general-knowledge-001",
        "smoke-knowledge-reapply-002",
        "早上涂过防晒，中午还需要再涂吗",
    ),
    (
        "offline-general-knowledge-001",
        "smoke-knowledge-reapply-003",
        "防晒补涂到底是在补什么",
    ),
    (
        "offline-consultation-multi-observation-001",
        "smoke-consultation-mixed-001",
        "脸有时候油有时候干，一换季还发红",
    ),
    (
        "offline-consultation-multi-observation-001",
        "smoke-consultation-mixed-002",
        "我一会儿出油一会儿又干，季节变化会红",
    ),
    (
        "offline-consultation-multi-observation-001",
        "smoke-consultation-mixed-003",
        "皮肤忽油忽干，换季脸颊还容易泛红",
    ),
    (
        "offline-safety-active-damage-001",
        "smoke-safety-damage-001",
        "脸已经破皮了还有点渗水",
    ),
    (
        "offline-safety-active-damage-001",
        "smoke-safety-damage-002",
        "现在皮肤破了还在渗出",
    ),
    (
        "offline-safety-active-damage-001",
        "smoke-safety-damage-003",
        "护肤后破皮渗液了怎么办",
    ),
    (
        "offline-product-knowledge-b5-001",
        "smoke-product-b5-001",
        "B5精华平时怎么用，质地黏不黏",
    ),
    (
        "offline-product-knowledge-b5-001",
        "smoke-product-b5-002",
        "想问B5精华的用法和肤感",
    ),
    (
        "offline-product-knowledge-b5-001",
        "smoke-product-b5-003",
        "B5精华是啥质地，早晚怎么安排",
    ),
    (
        "offline-comparison-two-serums-001",
        "smoke-comparison-serums-001",
        "B5精华跟CE精华主要差别在哪",
    ),
    (
        "offline-comparison-two-serums-001",
        "smoke-comparison-serums-002",
        "B5精华和CE精华放一起该怎么选",
    ),
    (
        "offline-comparison-two-serums-001",
        "smoke-comparison-serums-003",
        "帮我横向比一下B5精华、CE精华",
    ),
    (
        "offline-ambiguous-b5-clarification-001",
        "smoke-clarify-ambiguous-b5-001",
        "B5这东西具体怎么样",
    ),
    (
        "offline-followup-second-product-001",
        "smoke-followup-second-001",
        "我想继续看第二款的肤感",
    ),
    (
        "offline-followup-second-product-001",
        "smoke-followup-second-002",
        "刚才第二款怎么用",
    ),
    (
        "offline-budget-revision-001",
        "smoke-state-budget-correct-001",
        "预算改成100元以内吧",
    ),
    (
        "offline-return-product-focus-001",
        "smoke-state-return-focus-001",
        "回到之前那款，我想看用法",
    ),
    (
        "offline-pending-affirmation-001",
        "smoke-state-pending-affirm-001",
        "对",
    ),
)


def build_unified_router_smoke_cases(
    replays: Sequence[ReplayCase],
) -> tuple[RealUnifiedRouterCase, ...]:
    normalized = tuple(replays)
    if any(type(case) is not ReplayCase for case in normalized):
        raise TypeError("replays must contain exact ReplayCase values")
    by_id = {case.case_id: case for case in normalized}
    missing = set(_BASE_CATEGORIES) - set(by_id)
    if missing:
        raise ValueError(
            "smoke fixture is missing replay bases: "
            + ", ".join(sorted(missing))
        )
    base_cases = tuple(
        _prepare_smoke_case(
            base_id=replay.case_id,
            case=RealUnifiedRouterCase.from_replay_case(
                replay,
                category=_BASE_CATEGORIES[replay.case_id],
            ),
        )
        for replay in normalized
        if replay.case_id in _BASE_CATEGORIES
    )
    variants = tuple(
        _prepare_smoke_case(
            base_id=base_id,
            case=RealUnifiedRouterCase.from_replay_case(
                by_id[base_id],
                category=_BASE_CATEGORIES[base_id],
            ).model_copy(
                update={
                    "case_id": case_id,
                    "message": message,
                },
                deep=True,
            ),
        )
        for base_id, case_id, message in _VARIANTS
    )
    cases = (*base_cases, *variants)
    if len(cases) != 40:
        raise RuntimeError("unified router smoke fixture must have 40 cases")
    case_ids = tuple(case.case_id for case in cases)
    if len(case_ids) != len(set(case_ids)):
        raise RuntimeError(
            "unified router smoke fixture IDs must be unique"
        )
    return cases


def build_unified_router_smoke_v3_cases(
    replays: Sequence[ReplayCase],
) -> tuple[RealUnifiedRouterCase, ...]:
    cases = build_unified_router_smoke_cases(replays)
    return tuple(
        case.model_copy(
            update={
                "acceptable_semantic": (
                    case.acceptable_semantic.model_copy(
                        update={
                            "topic_hints": _union(
                                case.acceptable_semantic.topic_hints,
                                (None,),
                            )
                        },
                        deep=True,
                    )
                )
            },
            deep=True,
        )
        if case.case_id == "offline-confirmed-image-suitability-001"
        else case
        for case in cases
    )


def _prepare_smoke_case(
    *,
    base_id: str,
    case: RealUnifiedRouterCase,
) -> RealUnifiedRouterCase:
    semantic = case.acceptable_semantic
    operation_hints = semantic.operation_hints
    topic_hints = semantic.topic_hints
    continuity_hints = semantic.continuity_hints
    subject_scope_hints = semantic.subject_scope_hints

    if (
        case.starting_snapshot is None
        and case.expected_route.continuity == "replace_task"
    ):
        continuity_hints = _union(
            continuity_hints,
            ("new_task", "unknown"),
        )
    if case.category in {"consultation", "safety"}:
        topic_hints = _union(
            topic_hints,
            ("skincare", None),
        )
    if base_id == "offline-ambiguous-b5-clarification-001":
        operation_hints = _union(
            operation_hints,
            ("knowledge", "recommendation"),
        )
        topic_hints = _union(topic_hints, ("serum", None))
    if base_id == "offline-withdraw-exclusion-001":
        continuity_hints = _union(
            continuity_hints,
            ("continue", "return_to_focus"),
        )
    if base_id == "offline-return-product-focus-001":
        acceptable_task_modes = ("knowledge", "followup")
        acceptable_presentation_modes = (
            "product_knowledge",
            "followup",
        )
    else:
        acceptable_task_modes = case.acceptable_task_modes
        acceptable_presentation_modes = (
            case.acceptable_presentation_modes
        )
    if base_id != "offline-friend-profile-isolation-001":
        subject_scope_hints = _union(
            subject_scope_hints,
            ("self", "unknown"),
        )
    return case.model_copy(
        update={
            "acceptable_semantic": semantic.model_copy(
                update={
                    "operation_hints": operation_hints,
                    "topic_hints": topic_hints,
                    "continuity_hints": continuity_hints,
                    "subject_scope_hints": subject_scope_hints,
                },
                deep=True,
            ),
            "acceptable_task_modes": acceptable_task_modes,
            "acceptable_presentation_modes": (
                acceptable_presentation_modes
            ),
        },
        deep=True,
    )


def _union(values: tuple, additions: tuple) -> tuple:
    return tuple(dict.fromkeys((*values, *additions)))


__all__ = [
    "build_unified_router_smoke_cases",
    "build_unified_router_smoke_v3_cases",
]
