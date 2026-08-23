from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

from tools.guide_gates.continuous_conversation_fixture import (
    load_frozen_trajectories,
    normalize_message,
)
from tools.guide_gates.continuous_conversation_gate import (
    ContinuousTrajectory,
    ContinuousTurnExpectation,
)
from tools.guide_gates.continuous_conversation_mechanical_truth import (
    MechanicalTruthSpec,
    TruthCorrectionOverlay,
    apply_truth_correction_overlay,
)


ROOT = Path(__file__).resolve().parents[2]
FIXTURE_ROOT = ROOT / "tests/fixtures/guide/conversation"
AUDIT_ROOT = ROOT / "docs/audits/continuous-conversation"
SOURCE_FIXTURE = (
    FIXTURE_ROOT
    / "continuous_blind_b_replacement_20x5_v2.jsonl"
)
SOURCE_MANIFEST = (
    FIXTURE_ROOT
    / "continuous_blind_b_replacement_20x5_v2_manifest.json"
)
SOURCE_TRUTH = (
    FIXTURE_ROOT
    / "continuous_blind_b_replacement_20x5_v2_truth.json"
)
SOURCE_CORRECTION = (
    AUDIT_ROOT
    / "blind-b-replacement-v2-truth-correction-v1.json"
)
OUTPUT_FIXTURE = (
    FIXTURE_ROOT / "continuous_blind_c_20x5_v1.jsonl"
)
OUTPUT_MANIFEST = (
    FIXTURE_ROOT / "continuous_blind_c_20x5_v1_manifest.json"
)
OUTPUT_TRUTH = (
    FIXTURE_ROOT / "continuous_blind_c_20x5_v1_truth.json"
)


MESSAGES = (
    (
        "想给自己买修护精华，最多花三百元，先推荐几款。",
        "预算收紧到一百二，修护需求别变。",
        "单独看看玉泽屏障修护精华，告诉我准确名称、价格和功效。",
        "先问点常识，精华和面霜应该先涂哪个？",
        "再回玉泽屏障修护精华，它确认过的适用肤质有哪些？",
    ),
    (
        "我通勤用防晒，预算二百以内，只考虑有明确防晒标识的。",
        "比较一下安热沙小金瓶和怡思丁小蓝瓶的价格、SPF和PA。",
        "先只讲小蓝瓶，它的价格和已核实成分是什么？",
        "预算再降到一百以内，防晒标识这个条件保留。",
        "换成安热沙小金瓶和碧柔Biore水活防晒水润凝蜜对比，只说确认过的事实。",
    ),
    (
        "我想精简自己的护肤步骤，三百以内找偏修护的精华。",
        "修护不用卡死，改成保湿优先，预算还是三百。",
        "把B5精华已确认的成分和功效分别说清楚。",
        "插个通用问题，护肤叠得太多为什么会搓泥？",
        "回到选精华，对比B5精华和玉泽屏障修护精华的价格、功效。",
    ),
    (
        "给我挑三款百元内防晒，每款都必须查得到SPF。",
        "先展开安热沙小金瓶，核实商品名、价格和防晒等级。",
        "刚才推荐里的第四款也给我看看。",
        "我说错数量了，改成比较小金瓶、小蓝瓶和碧柔Biore水活防晒水润凝蜜。",
        "最后单看碧柔Biore水活防晒水润凝蜜，确认价格和PA。",
    ),
    (
        "我想看看刚才提到的那支防晒适不适合继续用。",
        "我说的是安热沙小金瓶，先展示它已核实的资料。",
        "顺带讲讲SPF和PA分别代表什么。",
        "回到安热沙小金瓶，再核对一次它的SPF和PA。",
        "把安热沙小金瓶和资生堂蓝胖子按价格、防晒标识做对比。",
    ),
    (
        "平时上班通勤，防晒通常多久补一次？",
        "接下来帮我选购，一百三以内，只要有明确防晒标识的。",
        "理肤泉特护清盈防晒乳 SPF50 PA++++的完整名称、价格和防晒等级是什么？",
        "先聊知识，UVA和UVB会怎样影响防晒选择？",
        "回到理肤泉特护清盈防晒乳 SPF50 PA++++，查它的品类和安全资料。",
    ),
    (
        "给自己买修护精华，预算先按几百块上下算。",
        "可以，就用刚才建议的上限继续挑。",
        "单独核对海蓝之谜精萃水的完整名称、价格和已知功效。",
        "现在把预算定到三百以内，修护要求继续。",
        "最后比较B5精华和玉泽屏障修护精华的价格、功效。",
    ),
    (
        "我想买修护精华，预算暂时按几百块上下估。",
        "不是这个区间，准确预算是一百五十以内。",
        "一般叠加精华时，为什么建议轻薄的先用？",
        "回到玉泽屏障修护精华，只看完整名称和已记录参考价。",
        "按已核实功效比较玉泽屏障修护精华和B5精华。",
    ),
    (
        "给我配日常通勤防晒，价格先按几百块上下估。",
        "这个范围先作废，等我给一个确切数字再继续。",
        "预算确定为一百以内，找三款能查到SPF的防晒。",
        "展开怡思丁小蓝瓶，核对名称、价格和防晒等级。",
        "不是一共三款吗？那第四款是哪支？",
    ),
    (
        "我正在看B5精华，先确认商品身份和价格。",
        "再补充这支已确认的成分、适用肤质。",
        "比较B5精华和玉泽屏障修护精华，重点看价格、功效。",
        "先离开商品，皮肤屏障不稳定一般会有什么表现？",
        "回到B5精华，这次只复核成分。",
    ),
    (
        "我想判断自己的肤质，下午鼻子出油，洗完脸两颊紧。",
        "更正一下，额头其实不油，主要是鼻翼出油。",
        "换季两颊偶尔会红，平时没有持续刺痛。",
        "结合前面这些情况，我的基础肤质更偏哪一类？",
        "结论里请区分偶尔泛红和真正过敏。",
    ),
    (
        "昨晚换了新产品后两颊又热又红，先帮我判断现在的情况。",
        "目前没有破皮或渗液，疼也不是持续的。",
        "情况变了，我抓破以后一直在渗液。",
        "破损位置还持续疼，现在应该先怎么处理？",
        "已经破皮渗液了，今晚还可以刷酸吗？",
    ),
    (
        "我白天T区容易油，但洗脸后两颊发紧，想判断肤质。",
        "紧绷只发生在洁面后，用普通保湿会缓解。",
        "中途看看B5精华，它的已知功效和适用肤质符合我这些需求吗？",
        "先回肤质判断，继续参考前面的出油和洁面后紧绷。",
        "接着开始选购，三百以内找兼顾修护、保湿的精华。",
    ),
    (
        "冬天我的两颊经常起皮，想重新判断肤质倾向。",
        "位置补充一下，只有面颊起皮，额头不会。",
        "刷酸后两天偶尔有轻微刺感，停用后会消失。",
        "平常用基础保湿一直没不适，也算进判断里。",
        "最后总结时，把稳定肤质和阶段性刺激分开说。",
    ),
    (
        "我隔几天会轻微泛红，想知道是不是短期波动。",
        "现在没有肿胀、破皮、持续疼痛或渗液。",
        "触发因素更正，不是换新产品，是刷酸第二天出现。",
        "现在突然肿了，抓破的位置还一直疼。",
        "这种状态先停哪些刺激步骤，什么情况要去线下处理？",
    ),
    (
        "我在给自己选防晒，先识别上传图里是哪件商品。",
        "图片这款在一百五预算内吗？它有没有明确防晒标识？",
        "以图中商品为参考，另找百元内、有明确防晒标识的替代。",
        "比较安热沙小金瓶和怡思丁小蓝瓶的价格、防晒标识。",
        "回到第一张上传图，只确认原图商品的名称和价格。",
    ),
    (
        "先认一下这张防晒包装正面图对应什么商品。",
        "按照已知价格，图中商品有没有超过一百元？",
        "参照图片商品找其他百元内防晒，而且候选要有SPF记录。",
        "先问常识，开封后的防晒保存时应避开什么环境？",
        "回到原图商品，确认它的价格和安全资料。",
    ),
    (
        "我上传了两款防晒，请按先后顺序识别两张图。",
        "图里这一支价格在一百以内吗？",
        "我明确问第二张，按已知价格判断是否百元内。",
        "按图片顺序比较第一张和第二张的商品名、价格。",
        "最后回第一张图，只复核它的防晒等级。",
    ),
    (
        "这两张防晒图都是我自己的，请先按图一、图二识别。",
        "把图一和图二对应商品的价格、安全资料放在一起比较。",
        "那第三张图对应商品卖多少钱？",
        "刚才是数量口误，实际只有两张，重新比较图一和图二的价格。",
        "第一张在一百五预算内吗？有没有明确SPF？",
    ),
    (
        "我要挑防晒，先绑定上传图片里的具体商品。",
        "按现有参考价，图中这款低于一百元吗？",
        "以原图商品作参照，推荐一百三以内且有防晒标识的其他款。",
        "比较怡思丁小蓝瓶和碧柔Biore水活防晒水润凝蜜的价格、防晒标识。",
        "最后回原图那款，核实商品名、价格和安全记录。",
    ),
)


def _line_hash(values: tuple[str, ...]) -> str:
    return sha256(
        (("\n".join(values)) + "\n").encode("utf-8")
    ).hexdigest()


def _all_prior_messages() -> set[str]:
    messages: set[str] = set()
    for path in FIXTURE_ROOT.glob("*.jsonl"):
        if path == OUTPUT_FIXTURE:
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line:
                continue
            payload = json.loads(line)
            for turn in payload.get("turns", ()):
                message = turn.get("message")
                if isinstance(message, str):
                    messages.add(normalize_message(message))
    return messages


def main() -> int:
    if len(MESSAGES) != 20 or any(
        len(messages) != 5 for messages in MESSAGES
    ):
        raise ValueError("Blind C requires exactly 20 x 5 messages")
    source = load_frozen_trajectories(
        SOURCE_FIXTURE,
        manifest_path=SOURCE_MANIFEST,
    )
    overlay = TruthCorrectionOverlay.model_validate_json(
        SOURCE_CORRECTION.read_text(encoding="utf-8"),
        strict=True,
    )
    source = apply_truth_correction_overlay(
        trajectories=source,
        overlay=overlay,
        fixture_path=SOURCE_FIXTURE,
        manifest_path=SOURCE_MANIFEST,
        mechanical_truth_path=SOURCE_TRUTH,
    )

    trajectories: list[ContinuousTrajectory] = []
    turn_id_map: dict[str, str] = {}
    for trajectory_index, (trajectory, messages) in enumerate(
        zip(source, MESSAGES, strict=True),
        start=1,
    ):
        trajectory_id = f"blindc-v1-{trajectory_index:02d}"
        turns: list[ContinuousTurnExpectation] = []
        for turn_index, (turn, message) in enumerate(
            zip(trajectory.turns, messages, strict=True),
            start=1,
        ):
            turn_id = f"{trajectory_id}-t{turn_index}"
            turn_id_map[turn.turn_id] = turn_id
            payload = turn.model_dump(mode="python")
            payload.update({"turn_id": turn_id, "message": message})
            turns.append(
                ContinuousTurnExpectation.model_validate(
                    payload,
                    strict=True,
                )
            )
        payload = trajectory.model_dump(mode="python")
        payload.update({
            "trajectory_id": trajectory_id,
            "turns": tuple(turns),
        })
        trajectories.append(
            ContinuousTrajectory.model_validate(
                payload,
                strict=True,
            )
        )

    normalized_messages = tuple(
        normalize_message(turn.message)
        for trajectory in trajectories
        for turn in trajectory.turns
    )
    if len(set(normalized_messages)) != 100:
        raise ValueError("Blind C messages must be unique")
    if set(normalized_messages).intersection(_all_prior_messages()):
        raise ValueError("Blind C collides with prior conversation fixtures")

    fixture_bytes = (
        b"\n".join(
            trajectory.model_dump_json().encode("utf-8")
            for trajectory in trajectories
        )
        + b"\n"
    )
    source_truth = MechanicalTruthSpec.model_validate_json(
        SOURCE_TRUTH.read_text(encoding="utf-8"),
        strict=True,
    )
    truth_payload = source_truth.model_dump(mode="json")
    for turn in truth_payload["turns"]:
        turn["turn_id"] = turn_id_map[turn["turn_id"]]
    truth_bytes = (
        json.dumps(
            truth_payload,
            ensure_ascii=False,
            indent=2,
        ).encode("utf-8")
        + b"\n"
    )

    source_manifest = json.loads(
        SOURCE_MANIFEST.read_text(encoding="utf-8")
    )
    trajectory_ids = tuple(
        trajectory.trajectory_id for trajectory in trajectories
    )
    messages = tuple(
        turn.message
        for trajectory in trajectories
        for turn in trajectory.turns
    )
    referenced_ids = sorted({
        product_id
        for trajectory in trajectories
        for turn in trajectory.turns
        for product_id in (
            *turn.expected_card_ids,
            *(
                binding.product_id
                for binding in turn.expected_bindings
            ),
        )
    })
    source_manifest.update({
        "blind_c_created": True,
        "blind_label": None,
        "canonical_product_ids_used": referenced_ids,
        "mechanical_truth_file": OUTPUT_TRUTH.name,
        "mechanical_truth_sha256": sha256(truth_bytes).hexdigest(),
        "normalized_messages_sha256": _line_hash(
            normalized_messages
        ),
        "normalized_unique_count": 100,
        "replacement_for": (
            "continuous_blind_b_replacement_20x5_v2.jsonl"
        ),
        "selected_file": OUTPUT_FIXTURE.name,
        "selected_ids_sha256": _line_hash(trajectory_ids),
        "selected_messages_sha256": _line_hash(messages),
        "selected_sha256": sha256(fixture_bytes).hexdigest(),
    })
    source_manifest["coverage_counts"][
        "seen_ledger_collisions"
    ] = 0
    manifest_bytes = (
        json.dumps(
            source_manifest,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ).encode("utf-8")
        + b"\n"
    )

    OUTPUT_FIXTURE.write_bytes(fixture_bytes)
    OUTPUT_TRUTH.write_bytes(truth_bytes)
    OUTPUT_MANIFEST.write_bytes(manifest_bytes)
    print(json.dumps({
        "status": "sealed",
        "trajectory_count": len(trajectories),
        "turn_count": len(messages),
        "unique_message_count": len(set(normalized_messages)),
        "fixture_sha256": sha256(fixture_bytes).hexdigest(),
        "truth_sha256": sha256(truth_bytes).hexdigest(),
        "manifest_sha256": sha256(manifest_bytes).hexdigest(),
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
