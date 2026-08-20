from __future__ import annotations

from collections.abc import Sequence

from tools.guide_gates.run_real_unified_router_gate import (
    RealUnifiedRouterCase,
)
from tools.guide_gates.unified_router_gate import ReplayCase
from tools.guide_gates.unified_router_smoke_fixture import (
    build_unified_router_smoke_v3_cases,
)


BlindGroup = tuple[str, str, tuple[str, ...]]


_A2_NO_HISTORY: tuple[BlindGroup, ...] = (
    (
        "offline-recommend-serum-001",
        "recommend",
        (
            "手里五百，皮肤容易敏，想把修护精华定下来",
            "敏皮买修护类精华怎么挑？价格卡在五百",
            "修护精华给两款吧，我脸容易敏，最多花500",
            "预算上限五百，目标是敏感皮能考虑的修护精华",
            "想收一瓶修护精华，敏感肤质，价位别越过五百",
            "500块够不够选敏皮修护精华，帮我筛一下",
            "我容易敏，修护精华别超五百，有合适的吗",
            "准备买修护精华：敏感肤质；可接受价≤500",
            "修护为主的精华，给敏皮用，价格压在500内",
            "给敏感皮挑修护精华，五百是最高预算",
            "只考虑500及以下，敏皮修护精华选什么",
            "敏感肤质、修护诉求、预算五百，直接给方案",
        ),
    ),
    (
        "offline-friend-profile-isolation-001",
        "friend",
        (
            "我妈油又容易敏，防晒控制五百以内，替她看看",
            "给男朋友买防晒，他油敏皮，价格不要上500",
            "同学问油敏肤质用什么防晒，预算最多500",
            "代朋友咨询：油皮敏感，防晒，五百以内",
            "对象是油敏皮，想帮她选防晒，钱别超过五百",
            "给家里人看防晒，不是我的肤质，她油且敏，预算500",
        ),
    ),
    (
        "offline-general-knowledge-001",
        "general",
        (
            "户外一整天，防晒为什么早涂一次撑不住",
            "防晒膜不是已经成了吗，为啥过会还要补",
            "流汗以后补防晒的原理是什么",
            "上午擦的防晒到下午会发生什么，为什么得重涂",
            "不补防晒会少掉哪部分保护",
            "防晒的补涂频率是由什么决定的",
        ),
    ),
    (
        "offline-consultation-multi-observation-001",
        "consult",
        (
            "同一张脸上午干下午油，天气一变还红，这是啥情况",
            "洗完觉得干，过会又泛油，换季会红",
            "皮肤干油交替，季节变化时发红，想判断下肤质",
            "有时油得快，有时又绷，换季脸会红",
            "状态不稳定，出油和发干都会有，转季就泛红",
            "一边觉得缺水一边冒油，换季还红，能帮我看看吗",
            "脸会油也会干，到了季节交替容易发红",
        ),
    ),
    (
        "offline-safety-active-damage-001",
        "safety",
        (
            "皮肤裂开还有液体渗出来，现在还能继续护肤吗",
            "脸上已经有破损并且在渗液，需要先做什么",
            "刚护肤完刺到破皮，还往外渗，怎么办",
            "有伤口样的破皮和渗出，产品是不是都先停",
            "皮肤表面破了还湿湿地渗液",
            "脸破损、渗出，这种状态能不能擦护肤品",
        ),
    ),
    (
        "offline-product-knowledge-b5-001",
        "product",
        (
            "B5精华放在护肤哪一步，吸收后黏不黏",
            "B5精华早晚都能抹吗，质感是水还是胶",
            "说说B5精华的涂法，还有上脸厚不厚",
            "B5精华一次用多少顺序怎样，肤感偏粘吗",
            "B5精华需要天天用吗，摸起来是什么质地",
            "用B5精华先水后精华？它会不会糊脸",
            "B5精华的使用频次、步骤和肤感一起讲下",
        ),
    ),
    (
        "offline-comparison-two-serums-001",
        "compare",
        (
            "B5精华与CE精华分别走什么路线，怎么二选一",
            "把CE精华和B5精华按核心差异列个对照",
            "如果只留一瓶，B5精华还是CE精华，依据是什么",
            "CE精华对比B5精华，适合场景差在哪",
            "B5精华、CE精华做个横向表，我想取舍",
        ),
    ),
    (
        "offline-ambiguous-b5-clarification-001",
        "clarify",
        (
            "别人只写了B5，这能确定是哪件产品吗",
            "B5指的究竟是什么，没全名能评价吗",
            "看到缩写B5，先确认它是哪款再说",
            "只知道叫B5，具体产品没说清，能判断吗",
            "卖家说B5，我不知道对应哪一款",
            "B5这个简称太宽了吧，具体是什么产品",
        ),
    ),
)


_A2_CONTEXTUAL: tuple[BlindGroup, ...] = (
    (
        "offline-followup-second-product-001",
        "followup",
        (
            "名单第二位那瓶，肤感单独讲",
            "排在二号的产品要放护肤哪一步",
            "只展开刚才第2个，它早上能用吗",
            "第二件别带过，告诉我质地",
            "候选二号怎么涂，晚上能不能用",
            "刚列的第二瓶会不会有黏感",
            "列表里第二个的用量和顺序呢",
            "我问的是排名第二那款，使用方法是什么",
        ),
    ),
    (
        "offline-budget-revision-001",
        "budget",
        (
            "其他要求照旧，价钱上限改成100",
            "五百太高，封顶换成一百",
            "把可接受价格收窄到100及以下",
            "预算这项重新设为一百块以内",
            "品类肤质别动，只把钱降到100",
            "最多只能出100，按这个重选",
        ),
    ),
    (
        "offline-return-product-focus-001",
        "return",
        (
            "结束这个知识话题，回前面聚焦商品说用法",
            "切回先前选中的那瓶，告诉我怎么使用",
            "我想返回原来的商品焦点，看看它的质地",
            "先前那一款继续讲，别聊现在这个话题了",
            "回到之前锁定的精华，它应该在哪步用",
        ),
    ),
    (
        "offline-pending-affirmation-001",
        "affirm",
        (
            "确认，就用刚才那个范围",
            "没问题，按你问的值继续",
            "我同意这个预算，往下选",
            "是这个数，继续",
        ),
    ),
    (
        "offline-pending-rejection-001",
        "reject",
        (
            "否，这个预算不是我想表达的",
            "先别确认，我要重新报价格",
            "这个数不对，等我补充",
            "不是这个范围，暂时不要继续",
        ),
    ),
    (
        "offline-withdraw-exclusion-001",
        "withdraw",
        (
            "把酒精禁用条件拿掉",
            "撤销之前对酒精的排除",
            "酒精可以接受了，删掉那项限制",
            "别再把含酒精的筛出去",
            "前面说避开酒精作废，继续推荐",
        ),
    ),
    (
        "offline-session-profile-projection-001",
        "profile",
        (
            "给自己选修护精华，最高500",
            "预算五百，继续找修护精华",
            "我想要修护类精华，价格不高于500",
            "五百元范围内重新看修护精华",
        ),
    ),
    (
        "offline-friend-profile-isolation-001",
        "friend",
        (
            "换成替朋友选：她油敏皮，防晒不超500",
            "这次使用者是室友，油皮易敏，防晒预算五百",
            "不要套我的肤质，帮对象找500内油敏肌防晒",
        ),
    ),
    (
        "offline-confirmed-image-suitability-001",
        "image",
        (
            "刚才图片对应那款，敏感肤质用着合适吗",
            "识别出的防晒对容易敏感的皮肤友好吗",
            "图片一里的商品，敏皮能不能考虑",
            "那张图确认的产品是否适配敏感肌",
            "图中这一支对敏感皮的适配信息是什么",
            "已识别的那款防晒，敏感肌适用性如何",
        ),
    ),
)


_B1_NO_HISTORY: tuple[BlindGroup, ...] = (
    (
        "offline-recommend-serum-001",
        "recommend",
        (
            "想要修护精华，皮肤挺容易闹敏，500是死上限",
            "预算就五百，敏感肤质的修护精华帮我挑",
            "敏皮，修护精华，价位0到500，咋选",
            "找修护型精华，我会敏，不能贵过500",
            "给个敏感肌修护精华清单，手头预算五百",
            "买精华主要修护，肤质易敏，价格≤500",
            "五百块内能买啥修护精华？我皮肤敏感",
            "别超500哈，想看适合敏皮的修护精华",
            "修护精华求推荐，敏感肌，用钱最多五百",
            "预算500/敏感皮/修护精华，帮选",
        ),
    ),
    (
        "offline-friend-profile-isolation-001",
        "friend",
        (
            "是替我爸看防晒：油皮还易敏，预算500",
            "给伴侣问的，她油敏肤质，防晒别高于五百",
            "用户不是我，是同事；油敏皮；防晒；500内",
            "我妹油皮又敏感，想给她买不超500的防晒",
            "朋友要防晒，肤质油且敏，预算上限五百",
            "代家人选油敏肌防晒，能接受的价格到500",
        ),
    ),
    (
        "offline-general-knowledge-001",
        "general",
        (
            "海边待着时，防晒隔段时间重擦是为什么",
            "防晒会被汗和摩擦弄掉多少，所以才补吗",
            "室外光照没变，为什么防晒保护会下降",
            "上午的防晒到傍晚还能保持原效果吗",
            "补涂防晒是在恢复成膜还是补足剂量",
            "坐窗边一天也需要补防晒吗，原理呢",
            "防晒一次涂够，为什么仍有重涂这件事",
        ),
    ),
    (
        "offline-consultation-multi-observation-001",
        "consult",
        (
            "鼻子会油但有时整脸干，转季泛红，属于哪类",
            "油、干都碰到过，天气变的时候脸发红",
            "一阵子出油一阵子起干感，还总在换季红",
            "脸不是单纯油或干，季节切换会泛红",
            "有时油亮有时干紧，转季红得明显",
            "干和油同时困扰我，换季又容易红",
            "肤况反复：会油、会干、季节变化会发红",
        ),
    ),
    (
        "offline-safety-active-damage-001",
        "safety",
        (
            "现在有破皮并持续渗液，护肤步骤该停吗",
            "脸上破损处有东西渗出，急着问能擦什么",
            "皮肤弄破了还在出液体，这时怎么处理",
            "已经不是泛红，是破开并渗水了",
            "伤到皮肤表面还有渗出，先暂停哪些东西",
            "破皮位置一直湿润渗液，可以继续用精华吗",
        ),
    ),
    (
        "offline-product-knowledge-b5-001",
        "product",
        (
            "B5精华搽法是啥，干后会有粘手感吗",
            "B5精华早晚用的先后顺序和质地",
            "B5精华到底在水后还是霜前，用起来厚重不",
            "问B5精华：频率？步骤？触感？",
            "B5精华怎么叠加其他护肤，会不会黏腻",
            "B5精华使用说明和上脸质感想一起了解",
            "B5精华每天的安排以及涂开的感觉",
        ),
    ),
    (
        "offline-comparison-two-serums-001",
        "compare",
        (
            "CE精华和B5精华放同一维度比较，结论怎么选",
            "B5精华 VS CE精华，主要取舍点列出来",
            "比较一下CE精华、B5精华各自更偏什么",
            "我在B5精华与CE精华中犹豫，帮我做决定",
            "B5精华和CE精华横向差异表能给一个吗",
            "两瓶精华B5和CE，使用方向有何不同",
        ),
    ),
    (
        "offline-ambiguous-b5-clarification-001",
        "clarify",
        (
            "B5只有俩字，具体指代不明吧",
            "问B5之前是不是得先说清产品全称",
            "我只拿到B5这个称呼，能对应唯一商品吗",
            "B5是哪一个系列或单品，先帮我确认",
            "没有品牌只说B5，你知道是哪款吗",
            "所谓B5可能不止一个吧，怎么判断",
        ),
    ),
)


_B1_CONTEXTUAL: tuple[BlindGroup, ...] = (
    (
        "offline-followup-second-product-001",
        "followup",
        (
            "把第②项的触感说细一点",
            "刚刚那个二号，步骤怎么排",
            "第二名产品只讲早晚用法",
            "列表第二支擦完会粘手吗",
            "二号候选在水乳前还是后",
            "上次列的第二件，展开使用频率",
            "先聚焦第二款，其他别重复",
        ),
    ),
    (
        "offline-budget-revision-001",
        "budget",
        (
            "价格改口：不超过一百",
            "我只能接受100封顶，之前数值替换掉",
            "预算栏改成≤100，别的原样",
            "钱少点，最高一百重新来",
            "将500改为100，继续按原诉求挑",
            "条件保留，预算由五百调到一百",
        ),
    ),
    (
        "offline-return-product-focus-001",
        "return",
        (
            "从现在的知识问题退回先前商品，问它用量",
            "把焦点还给之前那瓶，我要看肤感",
            "返回刚才选中的精华，不继续聊视黄醇",
            "前一个商品话题恢复，说说怎么涂",
            "回商品焦点：原来那款适合早上吗",
        ),
    ),
    (
        "offline-pending-affirmation-001",
        "affirm",
        (
            "可以，确认该预算",
            "对，就是你刚问的那个数",
            "确认无误，接着推荐",
            "嗯，那个范围没错",
        ),
    ),
    (
        "offline-pending-rejection-001",
        "reject",
        (
            "不确认，这不是我的预算",
            "否掉刚才的数，我重新说",
            "先停，价格理解错了",
            "不是那个值，别按它选",
        ),
    ),
    (
        "offline-withdraw-exclusion-001",
        "withdraw",
        (
            "解除无酒精要求",
            "之前的酒精排除不算了",
            "允许含酒精，把禁用项删除",
            "酒精这一项从避开清单移除",
            "撤回酒精限制，其余条件照旧",
        ),
    ),
    (
        "offline-session-profile-projection-001",
        "profile",
        (
            "我本人要500内的修护精华",
            "按五百上限给我找修护精华",
            "修护精华，预算范围截至500",
            "这次目标是五百以内的修护精华",
        ),
    ),
    (
        "offline-friend-profile-isolation-001",
        "friend",
        (
            "另一个人用，朋友油敏皮，找500下的防晒",
            "给同事选，不要继承我肤质：油敏肌防晒五百内",
            "替伴侣继续看，她油敏，防晒价格到500",
        ),
    ),
    (
        "offline-confirmed-image-suitability-001",
        "image",
        (
            "照片已确认那款，敏感皮适用不",
            "图1对应商品对敏皮是否友好",
            "上张图识别出的防晒，敏感肌可以选吗",
            "图片里的产品拿来给易敏皮用合适吗",
            "刚确认身份的这一支，敏感肤质适配怎样",
            "当前图中那款是否有敏感肌适用信息",
            "识别结果里的防晒，对敏感肌怎么样",
        ),
    ),
)


_NO_HISTORY_FRIEND_BASE = "offline-friend-profile-isolation-001"


def build_unified_router_blind_a2_cases(
    replays: Sequence[ReplayCase],
) -> tuple[RealUnifiedRouterCase, ...]:
    return _build_batch(
        replays,
        batch_id="a2",
        no_history_groups=_A2_NO_HISTORY,
        contextual_groups=_A2_CONTEXTUAL,
    )


def build_unified_router_blind_b1_cases(
    replays: Sequence[ReplayCase],
) -> tuple[RealUnifiedRouterCase, ...]:
    return _build_batch(
        replays,
        batch_id="b1",
        no_history_groups=_B1_NO_HISTORY,
        contextual_groups=_B1_CONTEXTUAL,
    )


def _build_batch(
    replays: Sequence[ReplayCase],
    *,
    batch_id: str,
    no_history_groups: Sequence[BlindGroup],
    contextual_groups: Sequence[BlindGroup],
) -> tuple[RealUnifiedRouterCase, ...]:
    bases = {
        case.case_id: case
        for case in build_unified_router_smoke_v3_cases(replays)
    }
    no_history = _expand_groups(
        bases,
        groups=no_history_groups,
        batch_id=batch_id,
        history_kind="nh",
        no_history=True,
    )
    contextual = _expand_groups(
        bases,
        groups=contextual_groups,
        batch_id=batch_id,
        history_kind="ctx",
        no_history=False,
    )
    if len(no_history) != 55 or len(contextual) != 45:
        raise RuntimeError(
            f"blind {batch_id} must contain 55 no-history and "
            "45 contextual cases"
        )
    cases = (*no_history, *contextual)
    if len(cases) != 100:
        raise RuntimeError(
            f"blind {batch_id} must contain exactly 100 cases"
        )
    case_ids = tuple(case.case_id for case in cases)
    messages = tuple(case.message for case in cases)
    if len(case_ids) != len(set(case_ids)):
        raise RuntimeError(f"blind {batch_id} case IDs must be unique")
    if len(messages) != len(set(messages)):
        raise RuntimeError(f"blind {batch_id} messages must be unique")
    return cases


def _expand_groups(
    bases: dict[str, RealUnifiedRouterCase],
    *,
    groups: Sequence[BlindGroup],
    batch_id: str,
    history_kind: str,
    no_history: bool,
) -> tuple[RealUnifiedRouterCase, ...]:
    cases: list[RealUnifiedRouterCase] = []
    for base_id, slug, messages in groups:
        base = bases[base_id]
        for index, message in enumerate(messages, start=1):
            case_id = (
                f"blind-{batch_id}-{history_kind}-{slug}-{index:03d}"
            )
            cases.append(
                _variant(
                    base,
                    case_id=case_id,
                    message=message,
                    no_history=no_history,
                    drop_profile=(
                        no_history
                        and base_id == _NO_HISTORY_FRIEND_BASE
                    ),
                )
            )
    return tuple(cases)


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


__all__ = [
    "build_unified_router_blind_a2_cases",
    "build_unified_router_blind_b1_cases",
]
