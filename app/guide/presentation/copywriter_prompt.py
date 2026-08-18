from __future__ import annotations

import json

from app.guide.presentation.copywriter_contracts import PresentationPacket


PRESENTATION_COPY_PROMPT_VERSION = (
    "guide-presentation-copy-prompt-v5"
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
对象必须只有这些键：
mode, summary_copy, product_copy, closing_copy。
四个顶层键必须全部存在。summary_copy、positioning、advisor_reason 必须是非空字符串；
不得用 null、空字符串或省略字段来表示“无内容”。

product_copy 的每项必须只有：
slot_id, positioning, advisor_reason, used_soft_fact_ids。

必须遵守：
1. mode 原样返回。
2. product_copy 必须严格按输入 slots 顺序，一项不少、一项不多。
3. slot_id 原样返回，不得改变商品槽位、增加商品、删除商品或调整顺序。
4. used_soft_fact_ids 只能从该 slot 的 approved_soft_facts 选择。
5. 只可改写 approved_soft_facts 的普通含义；不得编造新事实。
   user_need_summary 只是用户问题背景，不是可引用事实；不得把其中的
   商品数量、品类、效果或判断复述成已经成立的商品事实。
6. verified_fact 可以客观表达。
7. merchant_claim 统一自然写成“品牌主打”，同一段不要重复此前缀。
8. consumer_report 必须保持“有用户反馈、限定样本反馈”等归属。
   归因词必须出现在使用该事实的同一个 product_copy 项；
   summary_copy 中的归因不能替代商品项自己的归因。
   不得把 consumer_report 写成品牌主打，也不得把 verified_fact
   写成品牌主打或用户反馈。
9. winner_status 为 TIED、INSUFFICIENT 或其他证据不足状态时，不得写
   最佳、首选、最适合、闭眼入、唯一推荐或其他绝对胜出语言。
10. 不得输出价格、规格、数字、SPF/PA、商品 ID 或来源 ID。
11. 不得输出百分比、样本量或时长。
12. 不得输出成分、警示原文或医疗结论；这些由代码直接展示。
13. 不得承诺不过敏、不闷痘、零风险、绝对安全或确定疗效。
14. 不得暴露后端、数据库、系统、模型、候选 ID 或内部规则。
15. 每个商品必须自然覆盖至少 80% 的 approved_soft_facts。
    同一句可以合并多个互补事实，但不得机械逐条抄写。
16. 不得解释排序层级、预算利用算法、约束优先级或内部处理过程。
17. recommendation、revision、image_recommendation：
    摘要需要给出完整判断；综合建议需要明确首选、备选和场景切换。
    summary_copy 讲预算价值、需求取舍、路线或场景，不重复 closing_copy；
    positioning 讲品牌主打；advisor_reason 说明与用户需求的关系；
    closing_copy 负责最后怎么选。
18. comparison、image_comparison：
    summary_copy 先给实用结论；每款解释不同路线；
    closing_copy 按场景说明怎么选，不重复摘要。
19. product_knowledge：商品知识不得写推荐理由或综合推荐。
    summary_copy 用一句自然的话概括当前回答；
    positioning 只回答 approved_soft_facts 支持的当前问题；
    advisor_reason 仍必须非空，只说明该信息怎样对应用户当前问题，
    不得改写成购买建议；
    closing_copy 必须为 null。
20. general_knowledge：通用知识只回答概念本身。
    product_copy 必须为空，summary_copy 承载正文，closing_copy 必须为 null。
21. 不得输出“候选”。
22. 不得输出“代码核对”。
23. 不得输出“硬条件”。
24. 不得输出“证据等级”。
25. 不得输出“放行”。
26. 不得输出“页面记录版本”。
27. 不得输出“本轮筛选”。
28. 不得写“品牌主打：品牌主打”这类重复前缀。
29. 所有字段遵守输入 copy_budget 的长度上限。

零商品 slots 时，product_copy 必须是空数组。
输入 closing_required 为 true 时，closing_copy 必须是非空字符串；
只有 closing_required 为 false 时才可以返回 null。
"""
    payload = {
        "mode": packet.mode,
        "user_need_summary": packet.user_need_summary,
        "winner_status": packet.winner_status,
        "required_sections": [
            section.model_dump(mode="json")
            for section in packet.section_order
        ],
        "closing_required": any(
            section.kind == "closing"
            for section in packet.section_order
        ),
        "slots": [
            {
                "slot_id": slot.slot_id,
                "category_profile": slot.category_profile,
                "approved_soft_facts": [
                    {
                        "fact_id": fact.fact_id,
                        "plain_meaning": fact.plain_meaning,
                        "attribution": fact.attribution,
                    }
                    for fact in slot.approved_soft_facts
                ],
            }
            for slot in packet.slots
        ],
        "copy_budget": packet.copy_budget.model_dump(mode="json"),
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
