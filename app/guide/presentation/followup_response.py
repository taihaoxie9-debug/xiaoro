from app.guide.decision.contracts import FollowupDecisionResult
from app.guide.feedback.contracts import ConversationSnapshot
from app.guide.presentation.contracts import ProductCard, ProductCardFacts
from app.guide.presentation.response_planning import (
    build_product_card,
)
from app.guide.understanding.contracts import FollowupAction


_ORDINAL_LABELS = {
    1: "第一款",
    2: "第二款",
    3: "第三款",
    4: "第四款",
}


def build_followup_cards(
    result: FollowupDecisionResult,
    *,
    snapshot: ConversationSnapshot,
    product_facts: dict[int, ProductCardFacts],
) -> list[ProductCard]:
    if snapshot.recommendation_slot is None:
        raise ValueError("followup requires recommendation slot")
    references = {
        item.product_id: item
        for item in snapshot.recommendation_slot.candidates
    }
    cards: list[ProductCard] = []
    for product_id in result.selected_product_ids:
        reference = references[product_id]
        facts = product_facts[product_id]
        cards.append(
            build_product_card(
                facts,
                skin_match=reference.skin_match,
                matched_efficacies=reference.matched_efficacies,
            )
        )
    return cards


def build_followup_message(
    result: FollowupDecisionResult,
    *,
    product_facts: dict[int, ProductCardFacts],
) -> str:
    if result.status == "insufficient_evidence":
        return "这几款暂时缺少可直接比较的价格，先不勉强判断哪款更便宜。"
    names = [
        product_facts[product_id].name or f"商品 {product_id}"
        for product_id in result.selected_product_ids
    ]
    if result.action is FollowupAction.ORDINAL_REFERENCE:
        assert result.ordinal is not None
        label = _ORDINAL_LABELS[result.ordinal]
        return (
            f"你问的是{label}：{names[0]}。"
            f"这是上一轮展示顺序中的{label}。"
        )
    joined = "、".join(names)
    if result.status == "tied":
        return (
            f"这几款里，{joined} 的审核参考价并列最低；"
            "这只代表价格维度，不代表综合适配更好。"
        )
    return (
        f"这几款里，{joined} 的审核参考价最低；"
        "这只代表价格维度，不代表综合适配更好。"
    )
