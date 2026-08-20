from decimal import Decimal

from app.guide.decision.contracts import FollowupDecisionResult
from app.guide.feedback.contracts import (
    ConversationSnapshot,
    DisplayedCandidateRef,
    RecommendationQueryContext,
)
from app.guide.presentation.contracts import ProductCardFacts
from app.guide.presentation.followup_response import (
    build_followup_cards,
    build_followup_message,
)
from app.guide.retrieval.category_profiles import CategoryProfile
from app.guide.understanding.contracts import FollowupAction


def snapshot() -> ConversationSnapshot:
    return ConversationSnapshot(
        session_id="s-1",
        version=1,
        query_context=RecommendationQueryContext(
            category="serum",
            budget_minimum=None,
            budget_maximum=Decimal("500"),
            skin="sensitive",
            efficacy="repair",
            exclusions=[],
        ),
        candidates=[
            DisplayedCandidateRef(
                product_id=91,
                ordinal=1,
                skin_match="unknown",
                matched_efficacies=["修护"],
            ),
            DisplayedCandidateRef(
                product_id=38,
                ordinal=2,
                skin_match="unknown",
                matched_efficacies=["修护"],
            ),
        ],
    )


def presentation_facts(
    product_id: int,
    name: str,
) -> ProductCardFacts:
    return ProductCardFacts(
        product_id=product_id,
        category_profile=CategoryProfile.SKINCARE,
        category_fields=(),
        name=name,
        brand="测试品牌",
        category="精华",
        price=Decimal("88") if product_id == 91 else Decimal("294"),
        fact_warnings=[],
    )


def ordinal_result() -> FollowupDecisionResult:
    return FollowupDecisionResult(
        action=FollowupAction.ORDINAL_REFERENCE,
        ordinal=2,
        status="selected",
        source_candidate_ids=[91, 38],
        selected_product_ids=[38],
        evidence_refs=["ordinal=2"],
    )


def fourth_ordinal_result() -> FollowupDecisionResult:
    return FollowupDecisionResult(
        action=FollowupAction.ORDINAL_REFERENCE,
        ordinal=4,
        status="selected",
        source_candidate_ids=[91, 38, 55, 72],
        selected_product_ids=[72],
        evidence_refs=["ordinal=4"],
    )


def cheapest_result() -> FollowupDecisionResult:
    return FollowupDecisionResult(
        action=FollowupAction.CHEAPEST,
        ordinal=None,
        status="selected",
        source_candidate_ids=[91, 38],
        selected_product_ids=[91],
        evidence_refs=["price_min=88"],
    )


def test_ordinal_card_preserves_snapshot_evidence() -> None:
    cards = build_followup_cards(
        ordinal_result(),
        snapshot=snapshot(),
        product_facts={
            38: presentation_facts(38, "理肤泉新B5多效修护精华")
        },
    )
    assert [card.product_id for card in cards] == [38]
    assert cards[0].skin_match == "unknown"
    assert cards[0].matched_efficacies == ["修护"]


def test_followup_card_preserves_canonical_direct_display_facts() -> None:
    facts = presentation_facts(
        38,
        "理肤泉新B5多效修护精华",
    ).model_copy(
        update={
            "efficacy": ("修护", "补水保湿", "舒缓"),
            "efficacy_state": "known",
            "ingredients_present": ("维生素原B5（泛醇）",),
            "ingredients_present_state": "known",
            "suitable_skin": ("多种肤质适用",),
            "suitable_skin_state": "known",
        }
    )

    card = build_followup_cards(
        ordinal_result(),
        snapshot=snapshot(),
        product_facts={38: facts},
    )[0]

    assert {
        fact.field_key
        for fact in card.category_facts
        if fact.state == "known"
    } >= {
        "efficacy",
        "ingredients_present",
        "suitable_skin",
    }


def test_followup_messages_do_not_claim_comprehensive_winner() -> None:
    ordinal = build_followup_message(
        ordinal_result(),
        product_facts={
            38: presentation_facts(38, "理肤泉新B5多效修护精华")
        },
    )
    assert "第二款" in ordinal
    assert "综合最适合" not in ordinal

    cheapest = build_followup_message(
        cheapest_result(),
        product_facts={91: presentation_facts(91, "玉泽修护精华")},
    )
    assert "审核参考价最低" in cheapest
    assert "不代表综合适配更好" in cheapest


def test_fourth_ordinal_message_uses_visible_candidate_label() -> None:
    message = build_followup_message(
        fourth_ordinal_result(),
        product_facts={72: presentation_facts(72, "第四款测试精华")},
    )

    assert message == (
        "你问的是第四款：第四款测试精华。"
        "这是上一轮展示顺序中的第四款。"
    )
