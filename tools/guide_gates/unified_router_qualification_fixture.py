from __future__ import annotations

from collections.abc import Sequence

from tools.guide_gates.run_real_unified_router_gate import (
    RealUnifiedRouterCase,
)
from tools.guide_gates.unified_router_final_blind_fixture import (
    build_unified_router_blind_b1_cases,
)
from tools.guide_gates.unified_router_gate import ReplayCase
from tools.guide_gates.unified_router_smoke_fixture import (
    build_unified_router_smoke_v3_cases,
)


BlindGroup = tuple[str, str, tuple[str, ...]]


_A3_MESSAGE_REPLACEMENTS = {
    "blind-b1-nh-recommend-001": (
        "想要500以内的修护精华，我是敏感肌"
    ),
    "blind-b1-nh-recommend-002": (
        "预算五百以内，敏感肤质的修护精华帮我挑"
    ),
    "blind-b1-nh-recommend-003": (
        "敏感皮，修护精华，价位500以内，咋选"
    ),
    "blind-b1-nh-recommend-004": (
        "找500以内的修护型精华，我是敏感皮"
    ),
    "blind-b1-nh-recommend-006": (
        "买500以内的精华，主要修护，敏感肌"
    ),
    "blind-b1-nh-recommend-008": (
        "别超500哈，想看适合敏感皮的修护精华"
    ),
    "blind-b1-nh-friend-001": (
        "是替我爸看防晒：油敏肌，预算500"
    ),
    "blind-b1-nh-friend-005": (
        "朋友要防晒，肤质油敏肌，预算上限五百"
    ),
    "blind-b1-nh-friend-002": (
        "给伴侣问的，她油敏肤质，防晒五百以内"
    ),
    "blind-b1-nh-friend-006": (
        "代家人选油敏肌防晒，价格500以内"
    ),
    "blind-b1-nh-compare-006": (
        "两瓶里，B5精华和CE精华的使用方向有何不同"
    ),
    "blind-b1-ctx-friend-003": (
        "替伴侣选，她油敏肌，防晒价格500以内"
    ),
    "blind-b1-ctx-friend-001": (
        "另一个人用，朋友油敏皮，找500以内的防晒"
    ),
}


_B2_NO_HISTORY: tuple[BlindGroup, ...] = (
    (
        "offline-recommend-serum-001",
        "recommend",
        (
            "敏感肌想买500元内的修护精华，优先怎么选",
            "修护精华给敏感皮用，钱控制在五百以内",
            "修护精华预算500以内，我是敏感肌",
            "五百元封顶，敏感肌用的修护精华有哪些",
            "敏感皮要一款修护精华，价格不超过500",
            "预算别超过五百，帮敏感肌挑修护精华",
            "敏感肌修护精华怎么选，最多500块",
            "想看修护精华，敏感皮，500以内",
        ),
    ),
    (
        "offline-friend-profile-isolation-001",
        "friend",
        (
            "给表姐找防晒，她是油敏肌，预算五百以内",
            "替朋友挑500内防晒，她油敏肌",
            "使用者是油敏肌同事，防晒预算卡在500以内",
            "不是我用，家人油敏肌，防晒预算五百",
            "油敏肌使用者是对象，防晒限价500以内",
        ),
    ),
    (
        "offline-general-knowledge-001",
        "general",
        (
            "紫外线没停，早晨那层防晒为什么会不够",
            "防晒补涂和出汗、擦拭有什么关系",
            "在室外活动时，防晒保护为何会随时间变弱",
            "已经足量涂过，后面还要补的原因是什么",
            "防晒重涂主要弥补膜被破坏还是剂量流失",
            "长时间晒太阳只涂一次会有什么问题",
            "防晒何时需要补，判断依据是什么",
            "为什么户外越久越不能只靠早上那次防晒",
        ),
    ),
    (
        "offline-consultation-multi-observation-001",
        "consult",
        (
            "额头下午油，两颊洗完干，换季还会泛红",
            "鼻子容易出油，脸颊紧，天气变时会红",
            "T区油但两边干，季节交替会泛红",
            "洗脸后发紧，下午额头鼻子油，换季红",
            "换季发红，平时面中会油、脸侧会干",
            "脸颊偏干、鼻子偏油，换季状态更红",
            "干和油分区出现，天气变化还泛红",
            "皮肤既会油也会紧绷，换季易红",
        ),
    ),
    (
        "offline-safety-active-damage-001",
        "safety",
        (
            "脸上破皮并有渗液，还能上护肤品吗",
            "现在皮肤有破口、在渗出，应该先停什么",
            "新产品后破损渗液，这种情况怎么办",
            "皮肤已经破了而且往外渗水",
            "脸上有破损和渗出，是否需要尽快就医",
            "破皮处持续渗液，护肤还能继续吗",
            "已经渗出了，不只是泛红，还能擦防晒吗",
        ),
    ),
    (
        "offline-product-knowledge-b5-001",
        "product",
        (
            "B5精华是在水后用吗，质地会黏吗",
            "B5精华每天用几次，上脸厚不厚",
            "B5精华早晚怎么安排，肤感偏什么",
            "B5精华先后怎么叠，触感偏哪类",
            "B5精华涂完会粘吗，放在面霜前还是后",
            "B5精华怎样用，吸收速度和触感如何",
            "问B5精华的步骤、频次和肤感",
        ),
    ),
    (
        "offline-comparison-two-serums-001",
        "compare",
        (
            "B5精华和CE精华从功效路线到肤感怎么比较",
            "B5精华、CE精华做二选一，分别适合什么情况",
            "横向看B5精华与CE精华，核心差异有哪些",
            "B5精华对比CE精华，预算和使用场景怎么取舍",
            "在B5精华和CE精华之间选，重点看哪些区别",
            "B5精华跟CE精华做个表格比较",
        ),
    ),
    (
        "offline-ambiguous-b5-clarification-001",
        "clarify",
        (
            "B5这个名字不完整，先确认具体产品",
            "只说B5能绑定到唯一商品吗",
            "B5到底是精华还是别的，具体指哪款",
            "没有完整名称，B5应该先怎么确认",
            "问B5之前需要补品牌或品类吗",
            "B5对应的不止一个产品吧，先澄清",
        ),
    ),
)


_B2_CONTEXTUAL: tuple[BlindGroup, ...] = (
    (
        "offline-followup-second-product-001",
        "followup",
        (
            "前面第2款的质地再说详细点",
            "刚才第二款每天怎么用",
            "候选二号的使用顺序是什么",
            "只看列表第二项，它上脸黏吗",
            "排第二的那瓶早晚都能用吗",
            "第二个产品放在护肤哪一步",
        ),
    ),
    (
        "offline-budget-revision-001",
        "budget",
        (
            "保留原条件，预算上限改为100",
            "之前500太高，换成100以内",
            "把价格最大值调到一百",
            "预算只留100，其他不改",
            "按一百封顶重新推荐",
            "修护和敏感肌条件照旧，钱降到100",
        ),
    ),
    (
        "offline-return-product-focus-001",
        "return",
        (
            "回到先前聚焦的商品，我想问质地",
            "结束视黄醇话题，继续之前那款的用法",
            "把焦点切回原来那瓶，早晚怎么用",
            "返回前面选中的精华，看使用顺序",
            "不聊当前知识了，回之前商品",
        ),
    ),
    (
        "offline-pending-affirmation-001",
        "affirm",
        (
            "确认这个预算，继续推荐",
            "对，刚才的范围可以",
            "是的，就按你给的数",
            "没问题，这个预算我接受",
        ),
    ),
    (
        "offline-pending-rejection-001",
        "reject",
        (
            "不确认，我要重新说预算",
            "这个预算不对，先别选",
            "否，不是我想要的范围",
            "刚才的数理解错了，我再补",
        ),
    ),
    (
        "offline-withdraw-exclusion-001",
        "withdraw",
        (
            "去掉酒精排除",
            "不再要求排除酒精",
            "把排除酒精这个条件撤掉",
            "可以含酒精，前面那条限制取消",
            "酒精不再排除了，继续推荐",
        ),
    ),
    (
        "offline-session-profile-projection-001",
        "profile",
        (
            "500以内帮我找修护精华",
            "我想买修护精华，预算最多五百",
            "修护精华不超过500，给我推荐",
            "五百封顶看修护精华",
        ),
    ),
    (
        "offline-friend-profile-isolation-001",
        "friend",
        (
            "这轮给朋友找油敏肌防晒，500以内",
            "帮同事挑防晒，她油敏肌，预算五百",
            "改成给家人看，油敏肌防晒不超500",
            "不是我的肤质，对象油敏肌，防晒预算500",
        ),
    ),
    (
        "offline-confirmed-image-suitability-001",
        "image",
        (
            "当前识别的图片商品适合敏感肌吗",
            "图一对应的防晒对敏感皮友好吗",
            "刚确认的图片产品，敏感肌能考虑吗",
            "上张图那款防晒是否适配敏感肤质",
            "识别出的这款对敏感皮有适用信息吗",
            "图片中的防晒拿给敏感肌用怎么样",
            "当前图里那款，敏感肌使用合适吗",
        ),
    ),
)


_B3_NO_HISTORY: tuple[BlindGroup, ...] = (
    (
        "offline-recommend-serum-001",
        "recommend",
        (
            "我皮肤敏感，想在五百以内挑修护精华",
            "修护精华给敏感肌用，最高预算500",
            "敏感皮买精华主要看修护，五百封顶",
            "敏感肌修护精华，价格最多五百",
            "五百以内的修护精华，敏感皮该看谁",
            "我属于敏感肌，想看500以内的修护精华",
            "敏感肌、修护精华、预算500以内，给选择",
        ),
    ),
    (
        "offline-friend-profile-isolation-001",
        "friend",
        (
            "给哥哥买防晒，他油敏肌，预算500以内",
            "客户是朋友，油敏肌，想找五百内防晒",
            "油敏肌室友要防晒，手头最多五百",
            "替油敏肌家人问一款五百封顶的防晒",
            "油敏肌同事托我问，防晒预算不超过500",
            "帮女友选防晒：油敏肌；500以内",
        ),
    ),
    (
        "offline-general-knowledge-001",
        "general",
        (
            "补防晒时究竟是在补哪一种保护",
            "如果一直在户外，防晒为什么会越用越不够",
            "汗水和触碰会怎样影响防晒层",
            "防晒早晨涂足了，中间还要重擦的依据",
            "防晒保护随时间下降是成分失效还是膜被蹭掉",
            "什么时候必须补防晒，怎么判断",
            "全天只涂一次防晒为什么通常不够",
        ),
    ),
    (
        "offline-consultation-multi-observation-001",
        "consult",
        (
            "早上脸颊紧，下午鼻额油，换季会泛红",
            "T区出油、两颊干，转季时还会红",
            "洗后有紧绷感，过几小时鼻子油，天气变会泛红",
            "额头鼻翼油得快，脸侧却干，换季红",
            "脸部不同区域一边油一边干，季节变化会红",
            "有出油也有干紧，换季泛红更明显",
            "鼻头油、两颊干，转季皮肤容易红",
            "皮肤不稳定，干油都有，换季还泛红",
        ),
    ),
    (
        "offline-safety-active-damage-001",
        "safety",
        (
            "破皮处正在渗液，这时还能用防晒吗",
            "脸有破损并往外渗，需不需要马上停护肤",
            "皮肤已经渗出液体了，能继续擦精华吗",
            "不是单纯刺痛，已经破开渗水",
            "新护肤品后出现破皮渗液，先怎么办",
            "脸上破口还在渗出，是否该尽快看医生",
            "有破损和渗液时，任何新产品都先停吗",
        ),
    ),
    (
        "offline-product-knowledge-b5-001",
        "product",
        (
            "B5精华要在乳霜前涂吗，吸收后粘不粘",
            "B5精华一天安排几次，质地更像水还是凝胶",
            "B5精华的日常用量、顺序和肤感",
            "怎么使用B5精华，涂完会厚重吗",
            "B5精华早上和晚上分别怎么搭配",
            "B5精华放在水和面霜之间吗，触感如何",
            "想了解B5精华的涂法和黏腻度",
            "B5精华使用步骤是什么，上脸清不清爽",
        ),
    ),
    (
        "offline-comparison-two-serums-001",
        "compare",
        (
            "B5精华和CE精华在主打方向上怎么区分",
            "B5精华与CE精华横向比较后该怎么选",
            "B5精华、CE精华分别适合哪些使用场景",
            "把B5精华跟CE精华的核心信息放表里对照",
            "B5精华还是CE精华，选择取决于哪些差异",
            "比较B5精华和CE精华的路线与取舍",
        ),
    ),
    (
        "offline-ambiguous-b5-clarification-001",
        "clarify",
        (
            "B5这个简称能指向唯一一款吗",
            "只给B5两个字，具体商品需要怎么确认",
            "B5到底是哪类产品，先别直接评价",
            "我只知道B5，完整名称不清楚",
            "先帮我确认B5对应哪个具体单品",
            "B5可能有歧义吧，应该补什么信息",
        ),
    ),
)


_B3_CONTEXTUAL: tuple[BlindGroup, ...] = (
    (
        "offline-followup-second-product-001",
        "followup",
        (
            "刚才清单里的第二款，质地具体怎样",
            "前面第2个产品每天涂几回",
            "二号候选应该排在护肤哪一步",
            "只讲第二项的早晚使用方式",
            "排第二的那瓶会不会黏",
            "回到列表第二款，告诉我一次用多少",
            "第二个候选和面霜怎么叠",
        ),
    ),
    (
        "offline-budget-revision-001",
        "budget",
        (
            "之前条件全保留，把预算改为100以内",
            "上限从500降成100",
            "只调整价格：一百封顶",
            "预算最大值换成100，继续选",
            "肤质和修护不变，最多花100",
            "重新按100以内筛，别的照旧",
        ),
    ),
    (
        "offline-return-product-focus-001",
        "return",
        (
            "停止当前知识话题，返回先前商品看质地",
            "把对话切回之前聚焦那瓶，问它用法",
            "回到原先选中的精华，早上怎么安排",
            "先不聊视黄醇，继续前面商品的步骤",
            "恢复之前商品焦点，看看是否适合白天",
        ),
    ),
    (
        "offline-pending-affirmation-001",
        "affirm",
        (
            "同意这个预算，接着挑",
            "确认无误，就按该范围",
            "对，数值没问题",
            "可以，这个预算继续",
        ),
    ),
    (
        "offline-pending-rejection-001",
        "reject",
        (
            "这个预算不对，我重新提供",
            "不确认，先等我改数值",
            "否，刚才范围理解错了",
            "那个价格不是我的意思，暂停",
        ),
    ),
    (
        "offline-withdraw-exclusion-001",
        "withdraw",
        (
            "撤销酒精这个排除条件",
            "酒精允许使用，删除这项限制",
            "把酒精禁用条件删除",
            "不必再避开酒精",
            "之前的酒精排除作废",
        ),
    ),
    (
        "offline-session-profile-projection-001",
        "profile",
        (
            "修护精华按五百封顶来",
            "给我推荐五百以内的修护精华",
            "修护精华最高500，开始选",
            "修护精华预算以五百封顶",
        ),
    ),
    (
        "offline-friend-profile-isolation-001",
        "friend",
        (
            "本次对象换朋友：油敏肌，防晒五百封顶",
            "同事本人油敏肌，想把防晒控制在五百内",
            "替家人挑防晒，他油敏肌，价格不超500",
        ),
    ),
    (
        "offline-confirmed-image-suitability-001",
        "image",
        (
            "刚识别出来的商品适合敏感皮吗",
            "图一这款防晒对敏感肌合适不",
            "当前图片对应产品有敏感肌适用信息吗",
            "识别到的防晒给敏感皮用怎么样",
            "上张图片那支，敏感肤质能考虑吗",
            "图里的当前商品是否适配敏感肌",
            "图片识别结果这款防晒，敏感肌友好吗",
        ),
    ),
)


_B4_NO_HISTORY: tuple[BlindGroup, ...] = (
    (
        "offline-recommend-serum-001",
        "recommend",
        (
            "我脸比较容易闹情绪，想买500以内的修护精华",
            "手上最多五百预算，皮肤偏敏感，精华优先考虑修护",
            "给自己挑精华：敏感状态，重点修护，价格上限500元",
            "日常修护精华预算限定500以内，我本人皮肤容易不耐受",
            "按敏感皮修护这个方向配一瓶精华，总价控制在500以内",
            "预算卡到500以内，想找日常修护型精华，我肤质容易敏感",
            "五百以内选敏感皮能用的修护精华，直接给个方案",
        ),
    ),
    (
        "offline-friend-profile-isolation-001",
        "friend",
        (
            "不是我用，给姑姑选防晒；她油敏皮，预算500以内",
            "这次咨询对象是室友，油敏肌，防晒最多五百",
            "替同事找防晒，她皮肤又油又敏感，价格上限500",
            "给家里人挑一支防晒，使用者油敏，预算五百以内",
            "对象要买防晒，她是油敏肤质，最多能花500元",
        ),
    ),
    (
        "offline-general-knowledge-001",
        "general",
        (
            "通勤一整天时，早上成膜的防晒为什么不能管到晚上",
            "游泳擦汗之后重新涂防晒，主要是在恢复什么",
            "只要没晒红就可以不补防晒吗，背后的判断逻辑是什么",
            "隔着几小时再补防晒，和第一次涂足量有什么区别",
            "办公室和户外来回跑，补涂防晒该看时间还是活动",
            "防晒膜被口罩摩擦以后，保护能力会怎么变化",
        ),
    ),
    (
        "offline-consultation-multi-observation-001",
        "consult",
        (
            "洗脸后两边绷，午后鼻翼发亮，最近降温时脸会红",
            "额头下午出油，嘴角附近却起皮，用酸以后偶尔刺",
            "鼻头油得快但脸颊干，普通保湿不疼，换季才红",
            "早晨脸侧发紧，中午T区油，这种状态反复半年了",
            "两颊会干到起屑，鼻子容易油，新换精华后还会刺",
            "额头总油，两颊洗后紧，我分不清自己是什么皮",
            "天气冷时脸颊红，平时鼻翼油，洁面后全脸有点绷",
            "有时鼻子泛油，有时脸侧发干，保湿产品通常不会刺",
            "上午脸紧下午额头亮，泛红多在换季那几天出现",
            "脸颊干、鼻子油，偶尔起皮但没有破损渗出",
        ),
    ),
    (
        "offline-safety-active-damage-001",
        "safety",
        (
            "刚换护肤品后脸上裂开还往外渗，先做什么",
            "皮肤表面已经有破口和液体，今晚还能照常护理吗",
            "不是轻微发红，是有伤口在渗，我该继续擦东西吗",
            "脸上的破损一直湿湿的，像在渗出，应该怎么处理",
            "新东西上脸后皮肤破了，并且有液体流出来",
            "现在有破皮渗水，继续叠护肤会不会更糟",
            "局部裂开还渗液，这种状态要不要先停所有新品",
            "皮肤已经破损并有渗出物，还适合做日常护理吗",
            "护肤区域出现开裂和渗液，需要先去看医生吗",
            "脸上有开放性破损，摸起来还在渗，怎么办",
        ),
    ),
    (
        "offline-product-knowledge-b5-001",
        "product",
        (
            "B5精华按什么顺序上脸？我更关心用量和吸收后的触感",
            "早晚都能涂B5精华吗，一次几滴，后面接面霜怎么排",
            "想核对B5精华的使用频率，以及干后会不会有膜感",
            "B5精华在水类产品之前还是之后，肤感偏黏还是滑",
            "如果白天用B5精华，步骤、用量和后续叠加怎么安排",
            "请只讲B5精华怎么涂，以及它在脸上是厚还是轻",
            "B5精华需要每天两次吗，吸收后再抹乳霜行不行",
        ),
    ),
    (
        "offline-comparison-two-serums-001",
        "compare",
        (
            "把B5精华和CE精华按修护重点、肤感、使用时段做对照",
            "如果只能留一瓶，B5精华与CE精华分别赢在哪些场景",
            "从功效侧重和搭配难度拆开比较CE精华、B5精华",
            "B5精华对上CE精华，哪类需求各自更匹配",
            "同时看B5精华和CE精华，价格之外最值得比的是什么",
        ),
    ),
    (
        "offline-ambiguous-b5-clarification-001",
        "clarify",
        (
            "别人只说一个B5，我还缺哪些信息才能确认具体商品",
            "包装上就看到B5两个字，这样能判断具体是哪款吗",
            "我想查B5，但品牌和完整品名都没有，先怎么确认",
            "单凭B5这个简称，可以直接绑定到商品吗",
            "手头只有B5这个叫法，别猜，告诉我需要补什么",
        ),
    ),
)


_B4_CONTEXTUAL: tuple[BlindGroup, ...] = (
    (
        "offline-followup-second-product-001",
        "followup",
        (
            "清单排在第二的那个，早上用时应该接在哪一步",
            "只说二号商品，吸收后会不会影响后续面霜",
            "回看第②项，它一次大概要涂多少",
            "候选列表第二位能不能早晚都用",
            "我想知道第二瓶和水类产品的先后顺序",
            "先别讲其他的，第二款上脸后多久接下一步",
        ),
    ),
    (
        "offline-budget-revision-001",
        "budget",
        (
            "修护和肤质要求都别动，花费改成不超过100",
            "上一轮预算太宽了，现在只接受100以内",
            "其他照常，预算上限改为100以内",
            "保留当前选择方向，最高只能付100元",
            "条件原样，预算这一项改为100封顶",
        ),
    ),
    (
        "offline-return-product-focus-001",
        "return",
        (
            "把视黄醇解释放一边，回原先选中的商品看使用频率",
            "知识话题先暂停，我要继续问之前聚焦那瓶的肤感",
            "切回先前那件商品，白天叠防晒是否方便",
            "回到前面保存的商品焦点，看看它适不适合早晨",
            "别聊成分概念了，接着说原来那款一次用多少",
        ),
    ),
    (
        "offline-pending-affirmation-001",
        "affirm",
        (
            "嗯，确认该数值，可以继续往下挑",
            "没问题，数值就照这个执行，继续找合适的",
            "确认这个范围，接下来按它挑商品",
            "是该预算，后续不用再问我数值",
        ),
    ),
    (
        "offline-pending-rejection-001",
        "reject",
        (
            "这个数不对，我重新报预算",
            "先不确认，该范围理解错了",
            "刚才预算错了，等我补准确数字",
            "否，不是这个价格范围",
        ),
    ),
    (
        "offline-withdraw-exclusion-001",
        "withdraw",
        (
            "去掉之前对酒精的这个排除条件",
            "允许有酒精，前面那条限制去掉",
            "允许添加酒精，前面那条限制删掉",
            "可以添加酒精，之前这个限制删掉",
        ),
    ),
    (
        "offline-session-profile-projection-001",
        "profile",
        (
            "按500以内给我选一瓶偏修护的精华",
            "夜间修护精华按500以内预算安排，直接给我选择",
            "精华以修护为主，价格别超过500",
            "五百预算用在修护精华上，给个选择",
        ),
    ),
    (
        "offline-friend-profile-isolation-001",
        "friend",
        (
            "这次不是给我，替油敏皮朋友找500以内防晒",
            "同事本人皮肤出油又易敏，这次防晒采购限定在500以内",
            "另一个人要用：油敏肤质，防晒预算500以内",
            "按家人的油敏状态选防晒，价格上限五百",
        ),
    ),
    (
        "offline-confirmed-image-suitability-001",
        "image",
        (
            "刚才图片确认的那支防晒，敏感状态能不能用",
            "图里识别出的商品有适合敏感肌的资料吗",
            "敏感肌拿已确认的图一商品来用，适配结论是什么",
            "已确认图片中的产品，敏感肌用起来要注意什么",
            "图一绑定的那款是否适合容易泛红的人",
            "图片识别到的防晒，敏感肤质考虑可以吗",
            "继续看刚才那张图的商品，它对敏感皮适配吗",
            "当前图中确认的产品有没有敏感肌使用信息",
            "上图那支防晒，敏感肤质是否值得考虑",
        ),
    ),
)


_B5_NO_HISTORY: tuple[BlindGroup, ...] = (
    (
        "offline-recommend-serum-001",
        "recommend",
        (
            "给自己的敏感皮配修护精华，预算定在500元以内",
            "精华只看修护方向，皮肤容易敏感，五百块封顶",
            "我的预算是500以内，目标是给敏感肌买修护精华",
            "按500以内、敏感肤质、修护精华三个条件给方案",
            "皮肤耐受差，准备在500以内选一支修护类精华",
            "预算500以内，修护精华里哪些更适合敏感状态",
            "把500以内预算留给日常修护精华，使用者是敏感肌",
        ),
    ),
    (
        "offline-friend-profile-isolation-001",
        "friend",
        (
            "表弟本人油敏，想把500以内预算用于防晒，不是我咨询",
            "帮邻居问防晒：她油敏皮，预算按500以内处理",
            "同学是油敏肤质，托我用500以内预算采购防晒",
            "给姐姐做选择：油敏肤质、防晒、五百元以内",
            "油敏肌朋友实际使用，防晒按500以内找，别套我的画像",
        ),
    ),
    (
        "offline-general-knowledge-001",
        "general",
        (
            "防晒涂够量以后，过几个小时保护膜为何仍需要重补",
            "大太阳下边走边流汗，什么时候应把防晒重新涂一遍",
            "补涂防晒取决于紫外线时长，还是擦汗摩擦这些动作",
            "如果整天没洗脸，早上的防晒也会逐渐失去保护吗",
            "户外待半天，中间补防晒是在补剂量还是修补膜",
            "为什么室内久坐和运动出汗的防晒补涂频率不同",
        ),
    ),
    (
        "offline-consultation-multi-observation-001",
        "consult",
        (
            "洁面后脸颊发紧，下午鼻子发油，天气一变还会红",
            "鼻翼总出油，两边却干，刷酸那晚会刺",
            "额头容易亮，嘴周有点起皮，平常保湿不疼",
            "洗完脸全脸紧，过会儿T区油，这种情况经常出现",
            "两颊干、鼻头油，最近换新品后偶尔泛红",
            "下午额头油，脸侧会绷，已经这样好几个月",
            "换季时脸红，平日脸颊干，鼻翼又容易出油",
            "保湿时不刺，但用酸会红；另外鼻子油、脸颊干",
            "鼻子发亮和两颊起皮同时有，我到底偏什么肤质",
            "洗后紧绷、午后T区油，没有肿也没有破皮",
        ),
    ),
    (
        "offline-safety-active-damage-001",
        "safety",
        (
            "现在脸上有破口，还在往外渗液",
            "刚用新品就裂开渗水了，不是普通刺痛",
            "皮肤破损的位置持续有液体渗出来",
            "我脸上已经破皮，并且出现渗出物",
            "目前局部开裂、渗液，护肤先停了",
            "这不是泛红，皮肤有开放伤口还湿着",
            "破皮那里一直渗，状态没有停下来",
            "脸上有破损，表面还能看到渗出的液体",
            "护肤后皮肤裂了，现在还有渗液",
            "当前是破口加渗出，不是单纯干燥",
        ),
    ),
    (
        "offline-product-knowledge-b5-001",
        "product",
        (
            "B5精华一次用多少，应该接在水后还是乳霜前",
            "只查B5精华：每天频率、涂抹步骤、吸收后肤感",
            "B5精华白天用会不会黏，后续叠防晒怎么安排",
            "关于B5精华，我想知道质地、用量和早晚顺序",
            "B5精华涂上后多久能接下一层，平时一天几次",
            "请说明B5精华的使用方法，以及干后有没有粘感",
            "水、B5精华、面霜三者怎样排序，它本身厚重吗",
        ),
    ),
    (
        "offline-comparison-two-serums-001",
        "compare",
        (
            "对比B5精华和CE精华，列出定位、肤感与场景差别",
            "横向拆解两款：B5精华与CE精华，并给场景取舍",
            "比较CE精华与B5精华：各自强项、短板和适合时段",
            "B5精华、CE精华二选一，请按核心路线逐项对照",
            "把CE精华和B5精华放一起比较，哪些人分别更适合",
        ),
    ),
    (
        "offline-ambiguous-b5-clarification-001",
        "clarify",
        (
            "我只记得产品叫B5，别直接猜，先告诉我怎么锁定",
            "手里信息只有B5简称，能确认到具体单品吗",
            "想了解B5，可我没品牌也没完整名称，这种怎么查",
            "B5指的到底是什么商品，需要补哪部分包装信息",
            "看到别人说B5，但不知道是哪款，先帮我澄清",
        ),
    ),
)


_B5_CONTEXTUAL: tuple[BlindGroup, ...] = (
    (
        "offline-followup-second-product-001",
        "followup",
        (
            "继续看候选第②项，它在早间流程里放哪里",
            "列表二号每天用几回，吸收后再接什么",
            "前面第二瓶的肤感我还没弄明白，展开说说",
            "只问排第二那款：一次用量和使用顺序",
            "刚才二号商品适合放在水后还是霜前",
            "候选第二位早晚都能用吗，涂完会不会粘",
        ),
    ),
    (
        "offline-budget-revision-001",
        "budget",
        (
            "把原预算压到100以内，肤质和修护方向保持",
            "其他条件继续沿用，价格上限现在改100元",
            "修护、敏感都不变，只把花费调成一百封顶",
            "上一轮条件保留，预算从500改到100以内",
            "按最高100重新选，原来的要求别删除",
        ),
    ),
    (
        "offline-return-product-focus-001",
        "return",
        (
            "返回之前保存的商品焦点，再讲它的使用步骤",
            "回到先前选中的那瓶，暂停当前视黄醇话题",
            "恢复原商品焦点，我要问它白天使用的表现",
            "请切回前面聚焦的精华，继续说一次用量",
            "离开现在的知识解释，返回旧焦点看那款肤感",
        ),
    ),
    (
        "offline-pending-affirmation-001",
        "affirm",
        (
            "可以，确认这个范围，往下继续",
            "没错，就按该预算继续找",
            "是这个预算，开始推荐",
            "确认该数值，接着选商品",
        ),
    ),
    (
        "offline-pending-rejection-001",
        "reject",
        (
            "先别确认，这个数理解错了",
            "刚才范围不对，我再给一遍",
            "不确认该预算，等我重说",
            "这个价格不是，暂停一下",
        ),
    ),
    (
        "offline-withdraw-exclusion-001",
        "withdraw",
        (
            "可以添加酒精，前面这个条件取消",
            "允许有酒精，之前这个条件删掉",
            "可以含酒精，把条件移除",
            "酒精这项从排除清单删掉",
        ),
    ),
    (
        "offline-session-profile-projection-001",
        "profile",
        (
            "用于修护精华的支出限定500以内，开始选",
            "修护方向精华按500以内预算开始推荐",
            "想把五百预算用来买修护精华",
            "精华要偏修护，价格控制在500以内",
        ),
    ),
    (
        "offline-friend-profile-isolation-001",
        "friend",
        (
            "本次购买人改为油敏肌朋友，防晒预算限制500以内",
            "这回服务对象是家人，油敏皮，防晒预算五百",
            "咨询对象是油敏肌同事，防晒按500以内处理，不采用我的肤质",
            "另一个使用者是油敏肤质，想找500内防晒",
        ),
    ),
    (
        "offline-confirmed-image-suitability-001",
        "image",
        (
            "回到已确认的图片商品，它对敏感肌适用吗",
            "图一那支防晒如果给敏感皮用，结论怎样",
            "刚识别成功的产品有没有敏感肤质相关资料",
            "上一张图绑定的商品，容易泛红的人能考虑吗",
            "当前图片里的防晒对敏感状态是否友好",
            "继续问识别出的那款：敏感肌使用合不合适",
            "已确认图中商品身份，再看它是否适配敏感皮",
            "敏感肌相关的试用资料，在图一所绑商品里有没有",
            "上次识别到的防晒，敏感肤质用要注意什么",
        ),
    ),
)


_NO_HISTORY_FRIEND_BASE = "offline-friend-profile-isolation-001"


def build_unified_router_blind_a3_cases(
    replays: Sequence[ReplayCase],
) -> tuple[RealUnifiedRouterCase, ...]:
    source = build_unified_router_blind_b1_cases(replays)
    cases = tuple(
        _normalize_expectations(
            _rename_a3_case(case),
        )
        for case in source
    )
    return _validate_batch(cases, batch_id="a3")


def build_unified_router_blind_b2_cases(
    replays: Sequence[ReplayCase],
) -> tuple[RealUnifiedRouterCase, ...]:
    bases = {
        case.case_id: case
        for case in build_unified_router_smoke_v3_cases(replays)
    }
    no_history = _expand_groups(
        bases,
        groups=_B2_NO_HISTORY,
        batch_id="b2",
        history_kind="nh",
        no_history=True,
    )
    contextual = _expand_groups(
        bases,
        groups=_B2_CONTEXTUAL,
        batch_id="b2",
        history_kind="ctx",
        no_history=False,
    )
    return _validate_batch(
        tuple(
            _normalize_expectations(case)
            for case in (*no_history, *contextual)
        ),
        batch_id="b2",
    )


def build_unified_router_blind_a4_cases(
    replays: Sequence[ReplayCase],
) -> tuple[RealUnifiedRouterCase, ...]:
    source = build_unified_router_blind_b2_cases(replays)
    cases = tuple(
        _normalize_requalified_expectations(
            _rename_case(
                case,
                old_prefix="blind-b2-",
                new_prefix="blind-a4-",
            )
        )
        for case in source
    )
    return _validate_batch(cases, batch_id="a4")


def build_unified_router_blind_b3_cases(
    replays: Sequence[ReplayCase],
) -> tuple[RealUnifiedRouterCase, ...]:
    bases = {
        case.case_id: case
        for case in build_unified_router_smoke_v3_cases(replays)
    }
    no_history = _expand_groups(
        bases,
        groups=_B3_NO_HISTORY,
        batch_id="b3",
        history_kind="nh",
        no_history=True,
    )
    contextual = _expand_groups(
        bases,
        groups=_B3_CONTEXTUAL,
        batch_id="b3",
        history_kind="ctx",
        no_history=False,
    )
    cases = tuple(
        _normalize_requalified_expectations(
            _normalize_expectations(case)
        )
        for case in (*no_history, *contextual)
    )
    return _validate_batch(cases, batch_id="b3")


def build_unified_router_blind_b4_cases(
    replays: Sequence[ReplayCase],
) -> tuple[RealUnifiedRouterCase, ...]:
    bases = {
        case.case_id: case
        for case in build_unified_router_smoke_v3_cases(replays)
    }
    no_history = _expand_groups(
        bases,
        groups=_B4_NO_HISTORY,
        batch_id="b4",
        history_kind="nh",
        no_history=True,
    )
    contextual = _expand_groups(
        bases,
        groups=_B4_CONTEXTUAL,
        batch_id="b4",
        history_kind="ctx",
        no_history=False,
    )
    cases = tuple(
        _normalize_requalified_expectations(
            _normalize_expectations(case)
        )
        for case in (*no_history, *contextual)
    )
    return _validate_batch(cases, batch_id="b4")


def build_unified_router_blind_b5_cases(
    replays: Sequence[ReplayCase],
) -> tuple[RealUnifiedRouterCase, ...]:
    bases = {
        case.case_id: case
        for case in build_unified_router_smoke_v3_cases(replays)
    }
    no_history = _expand_groups(
        bases,
        groups=_B5_NO_HISTORY,
        batch_id="b5",
        history_kind="nh",
        no_history=True,
    )
    contextual = _expand_groups(
        bases,
        groups=_B5_CONTEXTUAL,
        batch_id="b5",
        history_kind="ctx",
        no_history=False,
    )
    cases = tuple(
        _normalize_requalified_expectations(
            _normalize_expectations(case)
        )
        for case in (*no_history, *contextual)
    )
    return _validate_batch(cases, batch_id="b5")


def _rename_a3_case(
    case: RealUnifiedRouterCase,
) -> RealUnifiedRouterCase:
    case_id = case.case_id.replace("blind-b1-", "blind-a3-", 1)
    starting_snapshot = case.starting_snapshot
    if starting_snapshot is not None:
        starting_snapshot = starting_snapshot.model_copy(
            update={"session_id": f"session-{case_id}"},
            deep=True,
        )
    return case.model_copy(
        update={
            "case_id": case_id,
            "message": _A3_MESSAGE_REPLACEMENTS.get(
                case.case_id,
                case.message,
            ),
            "starting_snapshot": starting_snapshot,
        },
        deep=True,
    )


def _rename_case(
    case: RealUnifiedRouterCase,
    *,
    old_prefix: str,
    new_prefix: str,
) -> RealUnifiedRouterCase:
    case_id = case.case_id.replace(old_prefix, new_prefix, 1)
    starting_snapshot = case.starting_snapshot
    if starting_snapshot is not None:
        starting_snapshot = starting_snapshot.model_copy(
            update={"session_id": f"session-{case_id}"},
            deep=True,
        )
    return case.model_copy(
        update={
            "case_id": case_id,
            "starting_snapshot": starting_snapshot,
        },
        deep=True,
    )


def _normalize_expectations(
    case: RealUnifiedRouterCase,
) -> RealUnifiedRouterCase:
    operation_hints = list(
        case.acceptable_semantic.operation_hints
    )
    acceptable_task_modes = list(case.acceptable_task_modes)
    acceptable_presentation_modes = list(
        case.acceptable_presentation_modes
    )
    if case.category == "clarification":
        operation_hints.append("clarification")
    if "-ctx-affirm-" in case.case_id:
        operation_hints.append("recommendation")
    if case.category == "image":
        operation_hints.append("followup")
        acceptable_task_modes.append("followup")
        acceptable_presentation_modes.append("followup")

    updates: dict[str, object] = {
        "acceptable_semantic": case.acceptable_semantic.model_copy(
            update={
                "operation_hints": tuple(
                    dict.fromkeys(operation_hints)
                )
            },
            deep=True,
        ),
        "acceptable_task_modes": tuple(
            dict.fromkeys(acceptable_task_modes)
        ),
        "acceptable_presentation_modes": tuple(
            dict.fromkeys(acceptable_presentation_modes)
        ),
    }
    if (
        case.category == "comparison"
        and case.message.index("CE精华")
        < case.message.index("B5精华")
    ):
        updates["expected_bindings"] = tuple(
            reversed(case.expected_bindings)
        )
        updates["expected_card_ids"] = tuple(
            reversed(case.expected_card_ids)
        )
    return case.model_copy(update=updates, deep=True)


def _normalize_requalified_expectations(
    case: RealUnifiedRouterCase,
) -> RealUnifiedRouterCase:
    operation_hints = list(
        case.acceptable_semantic.operation_hints
    )
    topic_hints = list(case.acceptable_semantic.topic_hints)
    acceptable_task_modes = list(case.acceptable_task_modes)
    acceptable_presentation_modes = list(
        case.acceptable_presentation_modes
    )
    if case.category == "safety":
        topic_hints.append("serum")
    if case.category == "clarification":
        topic_hints.append("skincare")
    if "-ctx-return-" in case.case_id:
        operation_hints.append("suitability")
        acceptable_task_modes.append("suitability")
        acceptable_presentation_modes.append("single_product")
    if case.category == "image":
        operation_hints.append("knowledge")
        acceptable_task_modes.append("knowledge")
        acceptable_presentation_modes.append("product_knowledge")
    return case.model_copy(
        update={
            "acceptable_semantic": (
                case.acceptable_semantic.model_copy(
                    update={
                        "operation_hints": tuple(
                            dict.fromkeys(operation_hints)
                        ),
                        "topic_hints": tuple(
                            dict.fromkeys(topic_hints)
                        ),
                    },
                    deep=True,
                )
            ),
            "acceptable_task_modes": tuple(
                dict.fromkeys(acceptable_task_modes)
            ),
            "acceptable_presentation_modes": tuple(
                dict.fromkeys(acceptable_presentation_modes)
            ),
        },
        deep=True,
    )


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


def _validate_batch(
    cases: tuple[RealUnifiedRouterCase, ...],
    *,
    batch_id: str,
) -> tuple[RealUnifiedRouterCase, ...]:
    no_history = tuple(
        case for case in cases if case.starting_snapshot is None
    )
    contextual = tuple(
        case for case in cases if case.starting_snapshot is not None
    )
    if len(no_history) != 55 or len(contextual) != 45:
        raise RuntimeError(
            f"blind {batch_id} must contain 55 no-history and "
            "45 contextual cases"
        )
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


__all__ = [
    "build_unified_router_blind_a3_cases",
    "build_unified_router_blind_a4_cases",
    "build_unified_router_blind_b2_cases",
    "build_unified_router_blind_b3_cases",
    "build_unified_router_blind_b4_cases",
    "build_unified_router_blind_b5_cases",
]
