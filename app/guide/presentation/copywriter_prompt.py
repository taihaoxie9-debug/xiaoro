from __future__ import annotations

import json

from app.guide.presentation.copywriter_contracts import (
    PresentationPacket,
    build_copywriter_section_specs,
)
from app.guide.presentation.copywriter_references import (
    build_copywriter_reference_map,
)


PRESENTATION_COPY_PROMPT_VERSION = (
    "guide-presentation-copy-prompt-v18"
)


def build_presentation_copy_messages(
    packet: PresentationPacket,
) -> tuple[dict[str, str], dict[str, str]]:
    if not isinstance(packet, PresentationPacket):
        raise TypeError("packet must be PresentationPacket")
    system = """\
你是小 ro 导购的展示文案员，只负责把代码批准的软事实说得自然、有导购感。
你不负责理解用户意图、绑定商品、检索、筛选、排序、安全判断或修改状态。

只返回一个严格 JSON 对象，禁止 Markdown、HTML、代码块和额外字段。
对象必须只有两个顶层键：mode, sections。
mode 原样返回。sections 必须与输入 writable_sections 完全同序、同数量。
不得增加、删除、合并、拆分或重排 section。

sections 每项必须只有：
kind, slot_id, content, advisor_reason。
content 是对象，只能包含 text, winner_claim, used_fact_ids, used_constraint_ids。
text 必须是非空字符串；winner_claim 必须是 none、not_selected 或 selected；
两个 ID 字段必须是数组，只能填写输入中出现的短引用，例如 f1、c1。
绝不能猜测、拼接或输出真实事实 ID、来源 ID 或其他长 ID。
advisor_reason 只在 advisor_reason_required=true 的 product section 出现，
它与 content 具有相同的对象结构；其他 section 的 advisor_reason 必须为 null。
slot_id 必须原样返回；没有 slot_id 的 section 必须返回 null。

必须遵守：
1. 每个 section 的 used_fact_ids 只能选择该 section 的 allowed_fact_ids；
   used_constraint_ids 只能选择该 section 的 allowed_constraint_ids。
2. content_source=constraints_only 的 section 必须把 used_fact_ids 返回为 []；
   它只能基于 user_need_summary、winner_status 和 allowed_constraint_ids
   写取舍、回答范围或下一步，不能描述任何商品属性、品牌主打、用户反馈
   或其他商品事实。
3. content_source=approved_facts 的 section 才能改写当前 section 的
   approved_soft_facts 普通含义；不得编造新事实。allowed_fact_ids 是可用范围，
   不是必须逐条复述。required_dimension_ids 才是当前 section 必须回答的维度；
   不得为凑覆盖率堆料。
   user_need_summary 只是用户问题背景，不是可引用事实；不得把其中的
   商品数量、品类、效果或判断复述成已经成立的商品事实。
4. verified_fact 可以客观表达。merchant_claim 与 consumer_report
   的可见归因前缀由后端按每个 copy block 的 used_fact_ids 统一绑定；
   文本中不要自行写“品牌主打”“用户反馈”等归因前缀。
   不得把 consumer_report 写成品牌主打或品牌事实，也不得把 verified_fact
   改写成商家宣称或消费者反馈。
5. winner_status 为 TIED、INSUFFICIENT 或其他信息不足状态时，不得写
   最佳、首选、最适合、闭眼入、唯一推荐或其他绝对胜出语言；
   也不得把 winner_claim 填为 selected。明确否定胜出时填 not_selected；
   没有谈胜出判断时填 none。
6. 不得输出价格、规格、SPF/PA、商品 ID、来源 ID、警示原文、医疗结论、
   后端、数据库、系统、模型、候选、代码核对、硬条件、证据等级、放行、
   页面记录版本、本轮筛选或内部处理过程。
7. 不得承诺不过敏、不闷痘、零风险、绝对安全或确定疗效。
8. 只有 approved_soft_facts 已明示的数字、成分、时长或样本量才可写入；
   不得从用户问题、常识或未给出的资料补写。
   数字、成分、时长或样本量必须在出现它的同一个文本块中填写对应
   used_fact_ids；不得借用另一个 section 或 advisor_reason 的引用。
9. 所有文本遵守对应 section 的 copy_max_chars。
"""
    specs = build_copywriter_section_specs(packet)
    reference_map = build_copywriter_reference_map(packet)
    facts_by_id = {
        fact.fact_id: fact
        for slot in packet.slots
        for fact in slot.approved_soft_facts
    }
    payload = {
        "mode": packet.mode,
        "user_need_summary": packet.user_need_summary,
        "winner_status": packet.winner_status,
        "allowed_winner_claims": (
            ["none", "not_selected", "selected"]
            if packet.winner_status in {"SELECTED", "WINNER"}
            else ["none", "not_selected"]
        ),
        "writable_sections": [
            {
                **spec.model_dump(mode="json"),
                "allowed_fact_ids": [
                    reference_map.fact_ref_by_id[fact_id]
                    for fact_id in spec.allowed_fact_ids
                ],
                "allowed_constraint_ids": [
                    reference_map.constraint_ref_by_id[constraint_id]
                    for constraint_id in spec.allowed_constraint_ids
                ],
                "approved_soft_facts": [
                    {
                        "fact_ref": (
                            reference_map.fact_ref_by_id[fact_id]
                        ),
                        "plain_meaning": (
                            facts_by_id[fact_id].plain_meaning
                        ),
                        "dimension_ids": (
                            facts_by_id[fact_id].dimension_ids
                        ),
                        "attribution": facts_by_id[fact_id].attribution,
                    }
                    for fact_id in spec.allowed_fact_ids
                ],
            }
            for spec in specs
        ],
    }
    return (
        {"role": "system", "content": system},
        {
            "role": "user",
            "content": json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
        },
    )


__all__ = [
    "PRESENTATION_COPY_PROMPT_VERSION",
    "build_presentation_copy_messages",
]
