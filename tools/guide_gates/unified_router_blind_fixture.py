from __future__ import annotations

from collections.abc import Sequence

from tools.guide_gates.run_real_unified_router_gate import (
    RealUnifiedRouterCase,
)
from tools.guide_gates.unified_router_gate import ReplayCase
from tools.guide_gates.unified_router_smoke_fixture import (
    build_unified_router_smoke_v3_cases,
)


BlindVariant = tuple[str, str, str]


_NO_HISTORY_VARIANTS: tuple[BlindVariant, ...] = (
    (
        "offline-recommend-serum-001",
        "blind-a-nh-rec-001",
        "预算别过500，敏感肌想选修护精华",
    ),
    (
        "offline-recommend-serum-001",
        "blind-a-nh-rec-002",
        "敏感皮求个修护精华，五百块封顶",
    ),
    (
        "offline-recommend-serum-001",
        "blind-a-nh-rec-003",
        "500元以内有啥敏感肌修护精华",
    ),
    (
        "offline-recommend-serum-001",
        "blind-a-nh-rec-004",
        "给我挑修护精华吧，敏感肌，预算最多五百",
    ),
    (
        "offline-recommend-serum-001",
        "blind-a-nh-rec-005",
        "修护向精华，敏皮能用的，别超过500",
    ),
    (
        "offline-recommend-serum-001",
        "blind-a-nh-rec-006",
        "想买敏感肌修护精华，控制在500内",
    ),
    (
        "offline-recommend-serum-001",
        "blind-a-nh-rec-007",
        "五百预算看修护精华，我是敏感皮",
    ),
    (
        "offline-recommend-serum-001",
        "blind-a-nh-rec-008",
        "敏感肌用的修护精华咋选？上限500",
    ),
    (
        "offline-recommend-serum-001",
        "blind-a-nh-rec-009",
        "帮忙找修护精华，预算500以内，皮肤偏敏感",
    ),
    (
        "offline-recommend-serum-001",
        "blind-a-nh-rec-010",
        "500封顶哈，想要敏感肌修护精华",
    ),
    (
        "offline-friend-profile-isolation-001",
        "blind-a-nh-friend-rec-001",
        "给我姐找油敏肌防晒，预算500以内",
    ),
    (
        "offline-friend-profile-isolation-001",
        "blind-a-nh-friend-rec-002",
        "室友油敏皮，想看五百以下的防晒",
    ),
    (
        "offline-friend-profile-isolation-001",
        "blind-a-nh-friend-rec-003",
        "帮朋友挑防晒，她油皮还敏感，500封顶",
    ),
    (
        "offline-friend-profile-isolation-001",
        "blind-a-nh-friend-rec-004",
        "不是我用，给对象看油敏肌防晒，别超500",
    ),
    (
        "offline-friend-profile-isolation-001",
        "blind-a-nh-friend-rec-005",
        "替同事问，油敏肌防晒最多五百",
    ),
    (
        "offline-friend-profile-isolation-001",
        "blind-a-nh-friend-rec-006",
        "给妹妹买防晒，油敏皮，预算控制500内",
    ),
    (
        "offline-friend-profile-isolation-001",
        "blind-a-nh-friend-rec-007",
        "朋友是油敏肌，500以内防晒咋选",
    ),
    (
        "offline-general-knowledge-001",
        "blind-a-nh-general-001",
        "晒一上午以后为啥还要补防晒",
    ),
    (
        "offline-general-knowledge-001",
        "blind-a-nh-general-002",
        "出门前涂了防晒，下午还得补一遍吗",
    ),
    (
        "offline-general-knowledge-001",
        "blind-a-nh-general-003",
        "防晒隔几个小时补一次是因为啥",
    ),
    (
        "offline-general-knowledge-001",
        "blind-a-nh-general-004",
        "一直在户外，早上的防晒为什么不够",
    ),
    (
        "offline-general-knowledge-001",
        "blind-a-nh-general-005",
        "补防晒到底补的是防护还是用量",
    ),
    (
        "offline-general-knowledge-001",
        "blind-a-nh-general-006",
        "通勤中午有必要重新涂防晒不",
    ),
    (
        "offline-consultation-multi-observation-001",
        "blind-a-nh-consult-001",
        "脸忽油忽干，每到换季还会红",
    ),
    (
        "offline-consultation-multi-observation-001",
        "blind-a-nh-consult-002",
        "有时候冒油有时候紧干，季节一变就泛红",
    ),
    (
        "offline-consultation-multi-observation-001",
        "blind-a-nh-consult-003",
        "皮肤状态乱，一阵油一阵干，换季就红",
    ),
    (
        "offline-consultation-multi-observation-001",
        "blind-a-nh-consult-004",
        "这脸时油时干，天一换季还发红",
    ),
    (
        "offline-consultation-multi-observation-001",
        "blind-a-nh-consult-005",
        "一会儿油光一会儿干巴，换季容易红",
    ),
    (
        "offline-consultation-multi-observation-001",
        "blind-a-nh-consult-006",
        "最近总是忽干忽油，到了换季又泛红",
    ),
    (
        "offline-consultation-multi-observation-001",
        "blind-a-nh-consult-007",
        "脸上出油和发干轮着来，季节变化还红",
    ),
    (
        "offline-consultation-multi-observation-001",
        "blind-a-nh-consult-008",
        "油和干来回切，换季也容易红",
    ),
    (
        "offline-safety-active-damage-001",
        "blind-a-nh-safety-001",
        "脸破了还往外渗水，现在咋办",
    ),
    (
        "offline-safety-active-damage-001",
        "blind-a-nh-safety-002",
        "护肤后已经破皮渗液了",
    ),
    (
        "offline-safety-active-damage-001",
        "blind-a-nh-safety-003",
        "皮肤有破口而且在渗出，还能涂东西吗",
    ),
    (
        "offline-safety-active-damage-001",
        "blind-a-nh-safety-004",
        "现在脸上破皮又渗水，先怎么处理",
    ),
    (
        "offline-safety-active-damage-001",
        "blind-a-nh-safety-005",
        "有一块皮破了，正往外渗液",
    ),
    (
        "offline-safety-active-damage-001",
        "blind-a-nh-safety-006",
        "皮肤破损还渗出，我是不是先停护肤",
    ),
    (
        "offline-product-knowledge-b5-001",
        "blind-a-nh-product-001",
        "B5精华日常怎么抹，肤感会不会粘",
    ),
    (
        "offline-product-knowledge-b5-001",
        "blind-a-nh-product-002",
        "问下B5精华，质地厚吗，早晚咋用",
    ),
    (
        "offline-product-knowledge-b5-001",
        "blind-a-nh-product-003",
        "B5精华用在水前还是水后，摸着黏不",
    ),
    (
        "offline-product-knowledge-b5-001",
        "blind-a-nh-product-004",
        "想了解B5精华的使用顺序和质地",
    ),
    (
        "offline-product-knowledge-b5-001",
        "blind-a-nh-product-005",
        "B5精华每天几次，涂开是什么感觉",
    ),
    (
        "offline-product-knowledge-b5-001",
        "blind-a-nh-product-006",
        "B5精华怎么搭护肤步骤，肤感如何",
    ),
    (
        "offline-product-knowledge-b5-001",
        "blind-a-nh-product-007",
        "B5精华上脸质地咋样，平常怎么用",
    ),
    (
        "offline-comparison-two-serums-001",
        "blind-a-nh-compare-001",
        "B5精华对上CE精华，差别主要在哪",
    ),
    (
        "offline-comparison-two-serums-001",
        "blind-a-nh-compare-002",
        "把B5精华跟CE精华横着比一下",
    ),
    (
        "offline-comparison-two-serums-001",
        "blind-a-nh-compare-003",
        "B5精华、CE精华二选一怎么挑",
    ),
    (
        "offline-comparison-two-serums-001",
        "blind-a-nh-compare-004",
        "B5精华和CE精华各自强在哪",
    ),
    (
        "offline-comparison-two-serums-001",
        "blind-a-nh-compare-005",
        "想知道B5精华与CE精华哪种路线更合适",
    ),
    (
        "offline-comparison-two-serums-001",
        "blind-a-nh-compare-006",
        "帮我看看B5精华、CE精华怎么取舍",
    ),
    (
        "offline-ambiguous-b5-clarification-001",
        "blind-a-nh-clarify-001",
        "只说B5的话，它到底怎么样",
    ),
    (
        "offline-ambiguous-b5-clarification-001",
        "blind-a-nh-clarify-002",
        "B5这个叫法对应哪款，先讲讲",
    ),
    (
        "offline-ambiguous-b5-clarification-001",
        "blind-a-nh-clarify-003",
        "我看到有人说B5，这个好用吗",
    ),
    (
        "offline-ambiguous-b5-clarification-001",
        "blind-a-nh-clarify-004",
        "B5咋样啊，具体是哪一个",
    ),
    (
        "offline-ambiguous-b5-clarification-001",
        "blind-a-nh-clarify-005",
        "想问个B5，值不值得看",
    ),
)


_CONTEXTUAL_VARIANTS: tuple[BlindVariant, ...] = (
    (
        "offline-followup-second-product-001",
        "blind-a-ctx-followup-001",
        "那第二款上脸是什么感觉",
    ),
    (
        "offline-followup-second-product-001",
        "blind-a-ctx-followup-002",
        "第二个产品平时怎么用",
    ),
    (
        "offline-followup-second-product-001",
        "blind-a-ctx-followup-003",
        "继续说第2款，它会黏吗",
    ),
    (
        "offline-followup-second-product-001",
        "blind-a-ctx-followup-004",
        "刚才排第二的那个，早晚都能用吗",
    ),
    (
        "offline-followup-second-product-001",
        "blind-a-ctx-followup-005",
        "我只想看第二款的质地",
    ),
    (
        "offline-followup-second-product-001",
        "blind-a-ctx-followup-006",
        "第二款呢？用在哪一步",
    ),
    (
        "offline-followup-second-product-001",
        "blind-a-ctx-followup-007",
        "把第二个再展开讲讲用法",
    ),
    (
        "offline-followup-second-product-001",
        "blind-a-ctx-followup-008",
        "前面第二款肤感偏啥",
    ),
    (
        "offline-followup-second-product-001",
        "blind-a-ctx-followup-009",
        "候选里排二的那瓶怎么涂",
    ),
    (
        "offline-followup-second-product-001",
        "blind-a-ctx-followup-010",
        "先别说别的，第二款质地如何",
    ),
    (
        "offline-budget-revision-001",
        "blind-a-ctx-budget-001",
        "那就把预算改成100以内",
    ),
    (
        "offline-budget-revision-001",
        "blind-a-ctx-budget-002",
        "太贵了，最多一百吧",
    ),
    (
        "offline-budget-revision-001",
        "blind-a-ctx-budget-003",
        "预算往下调，100元封顶",
    ),
    (
        "offline-budget-revision-001",
        "blind-a-ctx-budget-004",
        "改一下，上限只留100",
    ),
    (
        "offline-budget-revision-001",
        "blind-a-ctx-budget-005",
        "前面的条件不动，预算压到一百以内",
    ),
    (
        "offline-budget-revision-001",
        "blind-a-ctx-budget-006",
        "钱这块收紧到100以下",
    ),
    (
        "offline-return-product-focus-001",
        "blind-a-ctx-return-001",
        "先回到之前那瓶，我想问用法",
    ),
    (
        "offline-return-product-focus-001",
        "blind-a-ctx-return-002",
        "还是看刚才聚焦的那款，怎么涂",
    ),
    (
        "offline-return-product-focus-001",
        "blind-a-ctx-return-003",
        "把话题切回前面那瓶，它早晚都用吗",
    ),
    (
        "offline-return-product-focus-001",
        "blind-a-ctx-return-004",
        "回去说刚才那款，质地是什么样",
    ),
    (
        "offline-return-product-focus-001",
        "blind-a-ctx-return-005",
        "不聊视黄醇了，回到原来那款看使用顺序",
    ),
    (
        "offline-pending-affirmation-001",
        "blind-a-ctx-affirm-001",
        "嗯，对的",
    ),
    (
        "offline-pending-affirmation-001",
        "blind-a-ctx-affirm-002",
        "对，就按这个预算",
    ),
    (
        "offline-pending-affirmation-001",
        "blind-a-ctx-affirm-003",
        "是，我确认",
    ),
    (
        "offline-pending-affirmation-001",
        "blind-a-ctx-affirm-004",
        "没错，继续吧",
    ),
    (
        "offline-pending-rejection-001",
        "blind-a-ctx-reject-001",
        "不是这个意思",
    ),
    (
        "offline-pending-rejection-001",
        "blind-a-ctx-reject-002",
        "不对",
    ),
    (
        "offline-pending-rejection-001",
        "blind-a-ctx-reject-003",
        "不是，预算我重说",
    ),
    (
        "offline-pending-rejection-001",
        "blind-a-ctx-reject-004",
        "先不要，就不是这个数",
    ),
    (
        "offline-withdraw-exclusion-001",
        "blind-a-ctx-withdraw-001",
        "酒精这条排除取消掉",
    ),
    (
        "offline-withdraw-exclusion-001",
        "blind-a-ctx-withdraw-002",
        "不用再避开酒精了",
    ),
    (
        "offline-withdraw-exclusion-001",
        "blind-a-ctx-withdraw-003",
        "把不要酒精这个限制删了",
    ),
    (
        "offline-withdraw-exclusion-001",
        "blind-a-ctx-withdraw-004",
        "可以含酒精，前面那条撤掉",
    ),
    (
        "offline-withdraw-exclusion-001",
        "blind-a-ctx-withdraw-005",
        "酒精不排除了，继续选",
    ),
    (
        "offline-session-profile-projection-001",
        "blind-a-ctx-profile-001",
        "还是500以内的修护精华",
    ),
    (
        "offline-session-profile-projection-001",
        "blind-a-ctx-profile-002",
        "修护精华控制在五百以下",
    ),
    (
        "offline-session-profile-projection-001",
        "blind-a-ctx-profile-003",
        "想看修护向精华，预算500封顶",
    ),
    (
        "offline-session-profile-projection-001",
        "blind-a-ctx-profile-004",
        "五百内帮我找个修护精华",
    ),
    (
        "offline-friend-profile-isolation-001",
        "blind-a-ctx-friend-001",
        "这次给我同事找，油敏肌防晒500以内",
    ),
    (
        "offline-friend-profile-isolation-001",
        "blind-a-ctx-friend-002",
        "不是我，是朋友油敏皮，想看五百内防晒",
    ),
    (
        "offline-friend-profile-isolation-001",
        "blind-a-ctx-friend-003",
        "帮室友挑防晒，她油皮敏感，预算不超500",
    ),
    (
        "offline-confirmed-image-suitability-001",
        "blind-a-ctx-image-001",
        "这张图里的产品敏感肌能用吗",
    ),
    (
        "offline-confirmed-image-suitability-001",
        "blind-a-ctx-image-002",
        "图一那款对敏感皮友好吗",
    ),
    (
        "offline-confirmed-image-suitability-001",
        "blind-a-ctx-image-003",
        "刚识别的这支防晒适不适合敏感肌",
    ),
    (
        "offline-confirmed-image-suitability-001",
        "blind-a-ctx-image-004",
        "图片里的这款，我皮肤敏感可以考虑吗",
    ),
)


_NO_HISTORY_FRIEND_BASE = "offline-friend-profile-isolation-001"


def build_unified_router_blind_a_cases(
    replays: Sequence[ReplayCase],
) -> tuple[RealUnifiedRouterCase, ...]:
    bases = {
        case.case_id: case
        for case in build_unified_router_smoke_v3_cases(replays)
    }
    no_history = tuple(
        _variant(
            bases[base_id],
            case_id=case_id,
            message=message,
            no_history=True,
            drop_profile=base_id == _NO_HISTORY_FRIEND_BASE,
        )
        for base_id, case_id, message in _NO_HISTORY_VARIANTS
    )
    contextual = tuple(
        _variant(
            bases[base_id],
            case_id=case_id,
            message=message,
            no_history=False,
            drop_profile=False,
        )
        for base_id, case_id, message in _CONTEXTUAL_VARIANTS
    )
    cases = (*no_history, *contextual)
    if len(no_history) != 55 or len(contextual) != 45:
        raise RuntimeError(
            "blind A must contain 55 no-history and 45 contextual cases"
        )
    if len(cases) != 100:
        raise RuntimeError("blind A must contain exactly 100 cases")
    case_ids = tuple(case.case_id for case in cases)
    messages = tuple(case.message for case in cases)
    if len(case_ids) != len(set(case_ids)):
        raise RuntimeError("blind A case IDs must be unique")
    if len(messages) != len(set(messages)):
        raise RuntimeError("blind A messages must be unique")
    return cases


def _variant(
    base: RealUnifiedRouterCase,
    *,
    case_id: str,
    message: str,
    no_history: bool,
    drop_profile: bool,
) -> RealUnifiedRouterCase:
    expected_final_snapshot = base.expected_final_snapshot
    if drop_profile:
        expected_final_snapshot = {
            key: value
            for key, value in expected_final_snapshot.items()
            if key != "session_profile"
        }
    starting_snapshot = base.starting_snapshot
    if no_history:
        starting_snapshot = None
    elif starting_snapshot is None:
        raise ValueError(
            f"contextual blind case {case_id} requires a snapshot"
        )
    else:
        starting_snapshot = starting_snapshot.model_copy(
            update={"session_id": f"session-{case_id}"},
            deep=True,
        )
    return base.model_copy(
        update={
            "case_id": case_id,
            "message": message,
            "starting_snapshot": starting_snapshot,
            "expected_final_snapshot": expected_final_snapshot,
        },
        deep=True,
    )


__all__ = ["build_unified_router_blind_a_cases"]
