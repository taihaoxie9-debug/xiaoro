import csv
from copy import deepcopy
from pathlib import Path

import pytest

from app.guide.adapters.state import InMemoryConversationState
from app.guide.application import chat_api_adapter
from app.guide.application.chat_api_adapter import (
    ChatOwner,
    GuidePublicEventError,
    _card_to_frontend_product,
    classify_chat_owner,
    collect_guide_chat_response,
    iter_guide_public_events,
)
from app.guide.application.contracts import UserTurn
from app.guide.feedback.contracts import (
    ClarificationProgress,
    ConversationSnapshot,
)
from app.guide.presentation.sse_events import (
    ClarifyData,
    ClarifyEvent,
    EndData,
    EndEvent,
    GeneralKnowledgeCitationData,
    GeneralKnowledgeData,
    GeneralKnowledgeEvent,
    IntentData,
    IntentEvent,
    StartData,
    StartEvent,
)
from app.guide.retrieval.category_profiles import CategoryProfile
from app.guide.understanding.semantic_contracts import ClarificationCode
from app.guide_runtime.composition import (
    compose_text_recommendation_orchestrator as _compose_text_recommendation_orchestrator,
)
from tests.guide.semantic_test_port import exact_echo_understanding


def compose_text_recommendation_orchestrator(*args, **kwargs):
    kwargs.setdefault("understanding", exact_echo_understanding())
    return _compose_text_recommendation_orchestrator(*args, **kwargs)


OWNER_MATRIX = Path("docs/audits/phase2-day1/owner_matrix.csv")
_TASK29_CATEGORY_QUANTIFIERS = (
    "任意",
    "任一",
    "任何",
    "一切",
    "所有",
    "全部",
    "每个",
    "每一款",
    "每一种",
    "每一类",
    "各个",
    "各款",
    "各类",
    "这类",
    "这种",
    "这一类",
    "那种",
    "那一类",
)
_TASK30_NESTED_NEGATIVE_ATTRIBUTES = (
    "不含酒精的",
    "无酒精的",
    "无香精的",
)
_TASK32_OUTER_EXCLUSION_CUES = (
    "避开",
    "不要",
    "不想要",
    "排除",
    "拒绝",
    "不要有",
)
_TASK32_INNER_ABSENCE_CUES = ("不含", "无")
_TASK32_INGREDIENTS = ("酒精", "香精")
_TASK32_CATEGORIES = ("香水",)


def _turn(message: str) -> UserTurn:
    return UserTurn(
        session_id="s-1",
        message=message,
        image_bundle_id=None,
        conversation_version=0,
    )


def _presentation_payload(
    *,
    mode: str,
    product_ids: tuple[int, ...] = (),
) -> dict:
    if mode == "general_knowledge":
        responsibility = "general_knowledge"
        sections = [
            {
                "kind": "general_knowledge",
                "copy_text": "通用知识正文",
            }
        ]
    elif mode == "comparison":
        responsibility = "comparison"
        sections = [
            {"kind": "summary", "copy_text": "摘要"},
            {"kind": "comparison"},
            {"kind": "full_cards"},
        ]
    else:
        responsibility = "recommendation"
        sections = [{"kind": "summary", "copy_text": "摘要"}]
        sections.extend(
            {
                "kind": "product",
                "copy_text": "商品说明",
                "advisor_reason": "推荐理由",
                "slot_id": f"p{index}",
                "product_id": product_id,
                "direct_facts": [],
            }
            for index, product_id in enumerate(product_ids, start=1)
        )
        if product_ids:
            sections.extend(
                [
                    {"kind": "closing", "copy_text": "怎么选"},
                    {"kind": "full_cards"},
                ]
            )
        else:
            sections.append(
                {"kind": "closing", "copy_text": "怎么选"}
            )
    return {
        "responsibility": responsibility,
        "mode": mode,
        "copy_source": "fallback",
        "sections": sections,
        "comparison_rows": (
            [
                {
                    "dimension_id": "reference_price",
                    "label": "参考价",
                    "cells": [
                        {
                            "product_id": product_id,
                            "value": f"¥{product_id}",
                            "fact_ids": [f"fact:{product_id}:price"],
                            "state": "known",
                        }
                        for product_id in product_ids
                    ],
                }
            ]
            if mode == "comparison"
            else []
        ),
        "visible_product_ids": list(product_ids),
        "compact_tags": [],
        "card_display": (
            {
                "mode": "comparison",
                "visible_product_ids": list(product_ids),
                "max_cards": len(product_ids),
                "reason": "comparison",
            }
            if product_ids
            else {
                "mode": "none",
                "visible_product_ids": [],
                "max_cards": 0,
                "reason": None,
            }
        ),
        "telemetry": {
            "provider": "disabled",
            "model": "deterministic",
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "latency_ms": 0.0,
            "fallback_reason": "copywriter_disabled",
        },
    }


def test_image_recommend_intent_accepts_image_recommendation_presentation(
) -> None:
    presentation = chat_api_adapter._typed_presentation(
        _presentation_payload(mode="recommendation"),
        intent="image_recommend",
        names=["presentation_contract"],
    )

    assert presentation.mode == "recommendation"


def test_chat_adapter_preserves_typed_general_knowledge_event() -> None:
    event = GeneralKnowledgeEvent(
        data=GeneralKnowledgeData(
            query="SPF是什么意思",
            citations=[
                GeneralKnowledgeCitationData(
                    knowledge_id="a" * 64,
                    title="防晒怎么选",
                    section_title="怎么选",
                    public_excerpt="SPF针对UVB。",
                    source_path=(
                        "data/knowledge_docs/06-防晒怎么选.md"
                    ),
                    review_decision="general_answer",
                )
            ],
            educational_only=True,
            medical_escalation=False,
        )
    )

    name, data = chat_api_adapter._adapt_guide_event(event)

    assert name == "general_knowledge"
    assert data == event.data.model_dump(mode="json")


def test_collector_accepts_zero_card_general_knowledge_sequence() -> None:
    knowledge = {
        "query": "SPF是什么意思",
        "citations": [
            {
                "knowledge_id": "a" * 64,
                "title": "防晒怎么选",
                "section_title": "怎么选",
                "public_excerpt": "SPF针对UVB。",
                "source_path": (
                    "data/knowledge_docs/06-防晒怎么选.md"
                ),
                "review_decision": "general_answer",
            }
        ],
        "educational_only": True,
        "medical_escalation": False,
    }
    response = collect_guide_chat_response(
        [
            ("start", {"session_id": "knowledge-collector"}),
            (
                "intent",
                {
                    "intent": "knowledge",
                    "entities": {},
                    "scenario_intent": "knowledge",
                    "guide": True,
                },
            ),
            ("general_knowledge", knowledge),
            (
                "presentation_contract",
                _presentation_payload(mode="general_knowledge"),
            ),
            (
                "message",
                {
                    "content": "下面先讲通用知识。",
                    "done": False,
                },
            ),
            ("end", {"conversation_version": 1}),
        ],
        session_id="knowledge-collector",
        conversation_version=0,
    )

    assert response["general_knowledge"] == knowledge
    assert response["products"] == []
    assert response["response"] == ""
    assert response["conversation_version"] == 1


@pytest.mark.parametrize(
    "message",
    [
        "不要给我推荐防晒，推荐香水",
        "无需考虑防晒，推荐香水",
        "不想买防晒，推荐香水",
        "别再看防晒，推荐香水",
        "不需要任何防晒，推荐香水",
        "不要香水但要防晒",
        "不考虑香水改要防晒",
        "不考虑防晒但后来还是想买高端香水",
        "不考虑防晒以及后来还是想买高端香水",
        "不考虑防晒以及后来还是要买高端香水",
        "不考虑防晒以及后来还是想要高端香水",
        "不考虑防晒以及我后来还是想买高端香水",
        "不考虑防晒以及后来改买高端香水",
    ],
)
def test_clause_scoped_category_selection_is_owned_by_guide(
    message: str,
) -> None:
    assert classify_chat_owner(
        message=message,
        conversation_version=0,
        has_image_bundle_reference=False,
        has_legacy_image_payload=False,
    ) is ChatOwner.GUIDE_TEXT


@pytest.mark.parametrize(
    "message",
    [
        "不要给我推荐防晒和香水",
        "不需要任何防晒和香水",
        "不考虑防晒以及平价香水",
        "不考虑防晒以及高端香水",
        "不考虑防晒以及适合学生的香水",
    ],
)
def test_fully_negated_categories_are_clarified_by_guide(
    message: str,
) -> None:
    assert classify_chat_owner(
        message=message,
        conversation_version=0,
        has_image_bundle_reference=False,
        has_legacy_image_payload=False,
    ) is ChatOwner.GUIDE_TEXT


@pytest.mark.parametrize(
    "connector",
    ["并且", "并", "且", "以及"],
)
@pytest.mark.parametrize(
    "predicate",
    ["想买", "想要", "要买", "推荐", "改买"],
)
def test_task26_direct_positive_predicate_uses_guide_owner(
    connector: str,
    predicate: str,
) -> None:
    assert classify_chat_owner(
        message=f"不考虑防晒{connector}{predicate}平价香水",
        conversation_version=0,
        has_image_bundle_reference=False,
        has_legacy_image_payload=False,
    ) is ChatOwner.GUIDE_TEXT


@pytest.mark.parametrize(
    "message",
    [
        "不考虑防晒并不想买香水",
        "不考虑防晒并非要买香水",
        "不考虑防晒并想要避开的香水",
        "不考虑防晒并推荐避雷香水",
        "不考虑防晒并想买但不买香水",
        "不考虑防晒并改买香水但不要香水",
    ],
)
def test_task26_negative_category_state_uses_guide_owner(
    message: str,
) -> None:
    assert classify_chat_owner(
        message=message,
        conversation_version=0,
        has_image_bundle_reference=False,
        has_legacy_image_payload=False,
    ) is ChatOwner.GUIDE_TEXT


@pytest.mark.parametrize(
    "message",
    [
        "不甜的香水",
        "不贵的香水",
        "不含酒精的香水",
    ],
)
def test_task26_attribute_negation_uses_guide_owner(
    message: str,
) -> None:
    assert classify_chat_owner(
        message=message,
        conversation_version=0,
        has_image_bundle_reference=False,
        has_legacy_image_payload=False,
    ) is ChatOwner.GUIDE_TEXT


@pytest.mark.parametrize(
    "message",
    [
        "避开甜腻的香水",
        "不要太甜的香水",
        "不想要太甜的香水",
    ],
)
def test_task27_attribute_exclusion_uses_guide_owner(
    message: str,
) -> None:
    assert classify_chat_owner(
        message=message,
        conversation_version=0,
        has_image_bundle_reference=False,
        has_legacy_image_payload=False,
    ) is ChatOwner.GUIDE_TEXT


@pytest.mark.parametrize(
    "cue",
    ["不要", "避开", "排除", "拒绝"],
)
@pytest.mark.parametrize(
    "category_target",
    [
        "所有的",
        "所有",
        "全部的",
        "全部",
        "这类的",
        "这类",
        "这种的",
        "这种",
    ],
)
def test_task28_quantified_category_target_uses_guide_owner(
    cue: str,
    category_target: str,
) -> None:
    assert classify_chat_owner(
        message=f"{cue}{category_target}香水",
        conversation_version=0,
        has_image_bundle_reference=False,
        has_legacy_image_payload=False,
    ) is ChatOwner.GUIDE_TEXT


@pytest.mark.parametrize(
    "message",
    [
        "避开甜腻的香水",
        "不要太甜的香水",
        "不想要太甜的香水",
    ],
)
def test_task28_pure_attribute_target_uses_guide_owner(
    message: str,
) -> None:
    assert classify_chat_owner(
        message=message,
        conversation_version=0,
        has_image_bundle_reference=False,
        has_legacy_image_payload=False,
    ) is ChatOwner.GUIDE_TEXT


@pytest.mark.parametrize("cue", ["不要", "避开", "排除", "拒绝"])
@pytest.mark.parametrize("quantifier", _TASK29_CATEGORY_QUANTIFIERS)
@pytest.mark.parametrize("particle", ["", "的"])
def test_task29_closed_quantifier_set_uses_guide_owner(
    cue: str,
    quantifier: str,
    particle: str,
) -> None:
    assert classify_chat_owner(
        message=f"{cue}{quantifier}{particle}香水",
        conversation_version=0,
        has_image_bundle_reference=False,
        has_legacy_image_payload=False,
    ) is ChatOwner.GUIDE_TEXT


@pytest.mark.parametrize(
    "message",
    [
        "避开甜腻的香水",
        "不想要太甜的香水",
    ],
)
def test_task29_unsupported_sensory_exclusion_stays_guide_owned(
    message: str,
) -> None:
    assert classify_chat_owner(
        message=message,
        conversation_version=0,
        has_image_bundle_reference=False,
        has_legacy_image_payload=False,
    ) is ChatOwner.GUIDE_TEXT


@pytest.mark.parametrize("cue", ["不要", "避开", "排除", "不想要"])
@pytest.mark.parametrize(
    "attribute",
    _TASK30_NESTED_NEGATIVE_ATTRIBUTES,
)
def test_task30_nested_negative_attribute_stays_guide_owned(
    cue: str,
    attribute: str,
) -> None:
    assert classify_chat_owner(
        message=f"{cue}{attribute}香水",
        conversation_version=0,
        has_image_bundle_reference=False,
        has_legacy_image_payload=False,
    ) is ChatOwner.GUIDE_TEXT


@pytest.mark.parametrize(
    "message",
    [
        "不要含酒精的香水",
        "不含酒精的香水",
    ],
)
def test_task30_ordinary_ingredient_exclusion_stays_guide_owned(
    message: str,
) -> None:
    assert classify_chat_owner(
        message=message,
        conversation_version=0,
        has_image_bundle_reference=False,
        has_legacy_image_payload=False,
    ) is ChatOwner.GUIDE_TEXT


@pytest.mark.parametrize(
    "cue",
    ["不要有", "不要含", "不含", "不能有", "无"],
)
@pytest.mark.parametrize("ingredient", ["酒精", "香精"])
def test_task31_ingredient_exclusion_stays_guide_owned(
    cue: str,
    ingredient: str,
) -> None:
    assert classify_chat_owner(
        message=f"{cue}{ingredient}的香水",
        conversation_version=0,
        has_image_bundle_reference=False,
        has_legacy_image_payload=False,
    ) is ChatOwner.GUIDE_TEXT


@pytest.mark.parametrize("outer_cue", _TASK32_OUTER_EXCLUSION_CUES)
@pytest.mark.parametrize("inner_cue", _TASK32_INNER_ABSENCE_CUES)
@pytest.mark.parametrize("ingredient", _TASK32_INGREDIENTS)
@pytest.mark.parametrize("category", _TASK32_CATEGORIES)
def test_task32_nested_absence_stays_guide_owned(
    outer_cue: str,
    inner_cue: str,
    ingredient: str,
    category: str,
) -> None:
    assert classify_chat_owner(
        message=f"{outer_cue}{inner_cue}{ingredient}的{category}",
        conversation_version=0,
        has_image_bundle_reference=False,
        has_legacy_image_payload=False,
    ) is ChatOwner.GUIDE_TEXT


@pytest.mark.parametrize(
    "message",
    [
        "想要避开的香水",
        "推荐避雷香水",
        "想买但不买香水",
        "推荐防晒但不推荐防晒",
        "不考虑防晒并改买香水但最后不推荐香水",
    ],
)
def test_task27_effective_category_negation_uses_guide_owner(
    message: str,
) -> None:
    assert classify_chat_owner(
        message=message,
        conversation_version=0,
        has_image_bundle_reference=False,
        has_legacy_image_payload=False,
    ) is ChatOwner.GUIDE_TEXT


def test_guide_routes_supported_followups_without_category_words() -> None:
    for message in (
        "第二款呢",
        "哪个更便宜",
        "预算降到100元呢",
    ):
        assert classify_chat_owner(
            message=message,
            conversation_version=1,
            has_image_bundle_reference=False,
            has_legacy_image_payload=False,
            guide_conversation_claimed=True,
        ) is ChatOwner.GUIDE_TEXT
    assert classify_chat_owner(
        message="它怎么样",
        conversation_version=1,
        has_image_bundle_reference=False,
        has_legacy_image_payload=False,
        guide_conversation_claimed=True,
    ) is ChatOwner.GUIDE_TEXT


def test_owned_conversation_routes_open_text_to_parallel_understanding() -> None:
    for message in (
        "今天天气怎么样",
        "100元呢",
        "敏感肌适合吗",
        "不要酒精",
        "推荐精华油",
        "想买洁面仪",
        "粉底液还是口红",
    ):
        assert classify_chat_owner(
            message=message,
            conversation_version=1,
            has_image_bundle_reference=False,
            has_legacy_image_payload=False,
            guide_conversation_claimed=True,
        ) is ChatOwner.GUIDE_TEXT


@pytest.mark.parametrize(
    ("message", "version", "has_bundle", "legacy_image", "owner"),
    [
        ("500内油敏肌防晒", 0, False, False, ChatOwner.GUIDE_TEXT),
        (
            "500元内长时间户外防晒",
            0,
            False,
            False,
            ChatOwner.GUIDE_TEXT,
        ),
        ("第二款呢", 1, False, False, ChatOwner.GUIDE_TEXT),
        ("第二款呢", 0, False, False, ChatOwner.GUIDE_TEXT),
        ("找相似款", 0, True, False, ChatOwner.GUIDE_IMAGE),
        ("看看图片", 0, False, True, ChatOwner.GUIDE_TEXT),
        ("今天天气怎么样", 0, False, False, ChatOwner.GUIDE_TEXT),
    ],
)
def test_chat_owner_matrix(
    message: str,
    version: int,
    has_bundle: bool,
    legacy_image: bool,
    owner: ChatOwner,
) -> None:
    assert classify_chat_owner(
        message=message,
        conversation_version=version,
        has_image_bundle_reference=has_bundle,
        has_legacy_image_payload=legacy_image,
    ) is owner


def test_server_bundle_owner_precedes_untrusted_legacy_image_payload() -> None:
    assert classify_chat_owner(
        message="500内油敏肌防晒",
        conversation_version=0,
        has_image_bundle_reference=True,
        has_legacy_image_payload=True,
        consultation_claimed=True,
    ) is ChatOwner.GUIDE_IMAGE


def test_consultation_claim_precedes_text_guide_but_not_image_authority(
) -> None:
    assert classify_chat_owner(
        message="我不知道自己是什么肤质",
        conversation_version=0,
        has_image_bundle_reference=False,
        has_legacy_image_payload=False,
        consultation_claimed=True,
    ) is ChatOwner.GUIDE_CONSULTATION
    assert classify_chat_owner(
        message="我不知道自己是什么肤质",
        conversation_version=0,
        has_image_bundle_reference=False,
        has_legacy_image_payload=True,
        consultation_claimed=True,
    ) is ChatOwner.GUIDE_TEXT


def _successful_events() -> list[tuple[str, dict]]:
    cards = [
        {
            "type": "product_card",
            "product_id": product_id,
            "category_profile": "suncare",
            "category_facts": [
                {
                    "field_key": "spf_pa",
                    "label": "防晒指数",
                    "value": None,
                    "state": "unavailable",
                }
            ],
            "name": f"测试防晒 {product_id}",
            "brand": None,
            "category": None,
            "price": None,
            "image_url": None,
            "detail_url": None,
            "platform": None,
            "image_source_sha256": None,
            "skin_match": "unknown",
            "matched_efficacies": [],
            "fact_warnings": [],
        }
        for product_id in (53, 55)
    ]
    products = [
        _card_to_frontend_product(deepcopy(card))
        for card in cards
    ]
    comparison = {
        "status": "winner",
        "references": [
            {"ordinal": 1, "image_id": "image_" + "a" * 32, "product_id": 53},
            {"ordinal": 2, "image_id": "image_" + "b" * 32, "product_id": 55},
        ],
        "winner_reference": {
            "ordinal": 2,
            "image_id": "image_" + "b" * 32,
            "product_id": 55,
        },
        "tie_reason": None,
        "comparison_dimensions": ["price"],
        "evidence_refs": ["price:53", "price:55"],
        "evaluated_price_facts": [
            {
                "reference": {
                    "ordinal": 1,
                    "image_id": "image_" + "a" * 32,
                    "product_id": 53,
                },
                "state": "known",
                "value": "125",
                "source_refs": ["price:53"],
            },
            {
                "reference": {
                    "ordinal": 2,
                    "image_id": "image_" + "b" * 32,
                    "product_id": 55,
                },
                "state": "known",
                "value": "88.11",
                "source_refs": ["price:55"],
            },
        ],
    }
    return [
        ("start", {"session_id": "collector-session"}),
        (
            "image_observation",
            {
                "observation": {
                    "image_id": "image_" + "a" * 32,
                    "confirmed_product_id": 53,
                }
            },
        ),
        (
            "image_observation",
            {
                "observation": {
                    "image_id": "image_" + "b" * 32,
                    "confirmed_product_id": 55,
                }
            },
        ),
        ("intent", {"intent": "image_compare"}),
        (
            "decision_process",
            {
                "ordered_product_ids": [53, 55],
                "winner_status": "winner",
                "evidence_refs": ["price:53", "price:55"],
                "comparison_data": comparison,
                "decision_process": {
                    "steps": [
                        {
                            "data": {
                                "winner_status": "winner",
                                "products": 2,
                                "outcome": deepcopy(comparison),
                            }
                        }
                    ],
                    "final_recommendation": None,
                },
            },
        ),
        (
            "answer_contract",
            {
                "answer_contract": {
                    "product_count": 2,
                    "winner_status": "winner",
                    "has_unknown_skin": True,
                },
                "product_count": 2,
                "winner_status": "winner",
                "has_unknown_skin": True,
            },
        ),
        (
            "card_display_contract",
            {
                "mode": "comparison",
                "visible_product_ids": [53, 55],
                "max_cards": 2,
                "reason": "comparison",
            },
        ),
        (
            "products",
            {
                "products": products,
                "cards": cards,
            },
        ),
        (
            "presentation_contract",
            _presentation_payload(
                mode="comparison",
                product_ids=(53, 55),
            ),
        ),
        ("message", {"content": "comparison complete", "done": False}),
        ("end", {"conversation_version": 3}),
    ]


def test_collector_accepts_complete_comparison_and_zero_card_clarify() -> None:
    response = collect_guide_chat_response(
        _successful_events(),
        session_id="collector-session",
        conversation_version=2,
    )
    clarify = collect_guide_chat_response(
        [
            ("start", {"session_id": "collector-session"}),
            ("intent", {"intent": "clarify"}),
            (
                "message",
                {"content": "请补充信息", "done": False, "clarify": True},
            ),
            ("end", {"conversation_version": 2}),
        ],
        session_id="collector-session",
        conversation_version=2,
    )

    assert [item["id"] for item in response["products"]] == [53, 55]
    assert response["comparison_data"]["status"] == "winner"
    assert clarify["products"] == []
    assert clarify["card_display_contract"] is None
    assert clarify["response"] == "请补充信息"


@pytest.mark.parametrize("invalid_shape", ["mixed_profiles", "missing_facts"])
def test_collector_rejects_missing_or_mixed_card_category_profiles(
    invalid_shape: str,
) -> None:
    events = _successful_events()
    products_payload = next(
        data for name, data in events if name == "products"
    )
    if invalid_shape == "mixed_profiles":
        fragrance_fact = {
            "field_key": "sillage",
            "label": "扩香度",
            "value": None,
            "state": "unavailable",
        }
        for item in (
            products_payload["products"][1],
            products_payload["cards"][1],
        ):
            item["category_profile"] = "fragrance"
            item["category_facts"] = [fragrance_fact]
    else:
        products_payload["products"][0]["category_facts"] = []
        products_payload["cards"][0]["category_facts"] = []

    with pytest.raises(GuidePublicEventError) as caught:
        collect_guide_chat_response(
            events,
            session_id="collector-session",
            conversation_version=2,
        )

    assert caught.value.code == "GUIDE_EVENT_CONTRACT_INVALID"


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    [
        ("name", []),
        ("price", {}),
        ("image_url", 53),
        ("display_name", "drifted name"),
    ],
)
def test_collector_rejects_non_equivalent_public_product_projection(
    field_name: str,
    invalid_value,
) -> None:
    events = _successful_events()
    products_payload = next(
        data for name, data in events if name == "products"
    )
    products_payload["products"][0][field_name] = invalid_value

    _assert_collector_rejects(events)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda events: events[:-1],
        lambda events: [*events, ("message", {"content": "late"})],
        lambda events: [
            *events[:-1],
            ("end", {"conversation_version": 3}),
            ("end", {"conversation_version": 3}),
        ],
        lambda events: [
            events[0],
            events[3],
            events[5],
            events[7],
            events[6],
            events[8],
            events[9],
        ],
        lambda events: [
            *events[:5],
            (
                "answer_contract",
                {
                    "answer_contract": {
                        "product_count": 1,
                        "winner_status": "winner",
                        "has_unknown_skin": True,
                    }
                },
            ),
            *events[6:],
        ],
        lambda events: [
            *events[:7],
            (
                "products",
                {
                    "products": [
                        {"id": 55, "product_id": 55},
                        {"id": 53, "product_id": 53},
                    ],
                    "cards": [],
                },
            ),
            *events[8:],
        ],
        lambda events: [
            *events[:4],
            (
                "decision_process",
                {
                    **events[4][1],
                    "ordered_product_ids": [55, 53],
                },
            ),
            *events[5:],
        ],
    ],
)
def test_collector_rejects_incomplete_order_or_contract_mismatch(
    mutate,
) -> None:
    with pytest.raises(GuidePublicEventError) as caught:
        collect_guide_chat_response(
            mutate(_successful_events()),
            session_id="collector-session",
            conversation_version=2,
        )

    assert caught.value.code == "GUIDE_EVENT_CONTRACT_INVALID"


def test_collector_rejects_events_after_terminal_error() -> None:
    with pytest.raises(GuidePublicEventError) as caught:
        collect_guide_chat_response(
            [
                ("start", {"session_id": "collector-session"}),
                (
                    "error",
                    {
                        "error": "IMAGE_BUNDLE_UNAVAILABLE",
                        "message": "图片引用不可用，请重新上传。",
                    },
                ),
                ("message", {"content": "late"}),
            ],
            session_id="collector-session",
            conversation_version=0,
        )

    assert caught.value.code == "GUIDE_EVENT_CONTRACT_INVALID"


def _assert_collector_rejects(
    events: list[tuple[str, dict]],
) -> None:
    with pytest.raises(GuidePublicEventError) as caught:
        collect_guide_chat_response(
            events,
            session_id="collector-session",
            conversation_version=2,
        )

    assert caught.value.code == "GUIDE_EVENT_CONTRACT_INVALID"


def _set_comparison_statuses(
    events: list[tuple[str, dict]],
    status: str,
) -> None:
    decision = events[4][1]
    answer_event = events[5][1]
    decision["winner_status"] = status
    decision["decision_process"]["steps"][0]["data"][
        "winner_status"
    ] = status
    decision["comparison_data"]["status"] = status
    decision["decision_process"]["steps"][0]["data"]["outcome"][
        "status"
    ] = status
    answer_event["winner_status"] = status
    answer_event["answer_contract"]["winner_status"] = status


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(
            lambda events: events[4][1].__setitem__(
                "winner_status",
                "tie",
            ),
            id="decision-versus-answer",
        ),
        pytest.param(
            lambda events: events[4][1]["decision_process"]["steps"][0][
                "data"
            ].__setitem__("winner_status", "tie"),
            id="nested-decision-versus-decision",
        ),
        pytest.param(
            lambda events: events[5][1]["answer_contract"].__setitem__(
                "winner_status",
                "tie",
            ),
            id="answer-contract-versus-decision",
        ),
        pytest.param(
            lambda events: events[5][1].__setitem__(
                "winner_status",
                "tie",
            ),
            id="answer-wrapper-versus-contract",
        ),
        pytest.param(
            lambda events: events[4][1].__setitem__(
                "comparison_data",
                {
                    **events[4][1]["comparison_data"],
                    "status": "tie",
                },
            ),
            id="comparison-versus-decision",
        ),
        pytest.param(
            lambda events: events[4][1]["decision_process"]["steps"][0][
                "data"
            ].__setitem__(
                "outcome",
                {
                    **events[4][1]["comparison_data"],
                    "status": "tie",
                },
            ),
            id="nested-outcome-versus-comparison",
        ),
    ],
)
def test_collector_rejects_contradictory_producer_statuses(mutate) -> None:
    events = _successful_events()
    mutate(events)

    _assert_collector_rejects(events)


@pytest.mark.parametrize(
    "winner_reference",
    [
        pytest.param(
            {
                "ordinal": 2,
                "image_id": "image_" + "c" * 32,
                "product_id": 55,
            },
            id="foreign-image",
        ),
        pytest.param(
            {
                "ordinal": 2,
                "image_id": "image_" + "b" * 32,
                "product_id": 999,
            },
            id="foreign-product",
        ),
        pytest.param(
            {
                "ordinal": 1,
                "image_id": "image_" + "b" * 32,
                "product_id": 55,
            },
            id="foreign-ordinal",
        ),
    ],
)
def test_collector_rejects_winner_not_exactly_one_visible_reference(
    winner_reference: dict,
) -> None:
    events = _successful_events()
    events[4][1]["comparison_data"]["winner_reference"] = winner_reference
    events[4][1]["decision_process"]["steps"][0]["data"]["outcome"][
        "winner_reference"
    ] = deepcopy(winner_reference)

    _assert_collector_rejects(events)


@pytest.mark.parametrize(
    "status",
    ["tie", "insufficient_evidence"],
)
def test_collector_rejects_non_winner_status_with_winner_reference(
    status: str,
) -> None:
    events = _successful_events()
    _set_comparison_statuses(events, status)
    for comparison in (
        events[4][1]["comparison_data"],
        events[4][1]["decision_process"]["steps"][0]["data"]["outcome"],
    ):
        comparison["tie_reason"] = (
            "equal_price" if status == "tie" else None
        )
        if status == "tie":
            comparison["evaluated_price_facts"][1]["value"] = "125"

    _assert_collector_rejects(events)


def test_collector_rejects_winner_status_without_winner_reference() -> None:
    events = _successful_events()
    events[4][1]["comparison_data"]["winner_reference"] = None
    events[4][1]["decision_process"]["steps"][0]["data"]["outcome"][
        "winner_reference"
    ] = None

    _assert_collector_rejects(events)


def test_collector_rejects_price_fact_reference_not_exactly_ordered() -> None:
    events = _successful_events()
    for comparison in (
        events[4][1]["comparison_data"],
        events[4][1]["decision_process"]["steps"][0]["data"]["outcome"],
    ):
        comparison["evaluated_price_facts"][1]["reference"] = {
            "ordinal": 2,
            "image_id": "image_" + "c" * 32,
            "product_id": 55,
        }

    _assert_collector_rejects(events)


def test_historical_owner_matrix_legacy_rows_migrate_to_guide() -> None:
    with OWNER_MATRIX.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))

    assert [row["case_id"] for row in rows] == [
        "category_text",
        "category_skincare",
        "category_suncare",
        "category_base_makeup",
        "category_color_makeup",
        "category_cleanser",
        "category_fragrance",
        "scenario_text",
        "owned_followup",
        "legacy_followup",
        "server_bundle",
        "server_single_image_suitability",
        "server_two_image_bundle",
        "server_four_image_bundle",
        "legacy_image",
        "consultation_entry",
        "consultation_active_turn",
        "unsupported_text",
    ]
    for row in rows:
        owner = classify_chat_owner(
            message=row["message"],
            conversation_version=int(row["conversation_version"]),
            has_image_bundle_reference=row["image_bundle"] == "true",
            has_legacy_image_payload=row["legacy_image"] == "true",
            consultation_claimed=(
                row["consultation_claimed"] == "true"
            ),
        )
        expected_owner = (
            ChatOwner.GUIDE_TEXT.value
            if row["expected_owner"] == "legacy"
            else row["expected_owner"]
        )
        assert owner.value == expected_owner


def test_intent_category_profile_is_typed_and_safely_adapted() -> None:
    class CategoryIntentOrchestrator:
        def stream(self, turn):
            del turn
            yield IntentEvent(
                data=IntentData(
                    mode="recommend",
                    category_profile=CategoryProfile.BASE_MAKEUP,
                )
            )

    events = list(
        iter_guide_public_events(
            CategoryIntentOrchestrator(),
            _turn("推荐持妆粉底液"),
        )
    )

    assert events == [
        (
            "intent",
            {
                "intent": "recommend",
                "entities": {},
                "scenario_intent": "recommend",
                "guide": True,
                "category_profile": "base_makeup",
            },
        )
    ]


def test_slice1_guide_events_keep_frontend_product_shape(
    real_reader,
    real_product_assets,
) -> None:
    orchestrator = compose_text_recommendation_orchestrator(
        real_reader,
        product_assets=real_product_assets,
    )

    events = list(
        iter_guide_public_events(
            orchestrator,
            _turn("500 内适合油敏肌的防晒"),
        )
    )

    names = [name for name, _ in events]
    assert names[0] == "start"
    assert names[-1] == "end"
    products = next(data for name, data in events if name == "products")
    assert [item["id"] for item in products["products"]] == [101, 26, 52]
    card_display = next(
        data
        for name, data in events
        if name == "card_display_contract"
    )
    assert card_display == {
        "mode": "recommendation",
        "visible_product_ids": [101, 26, 52],
        "max_cards": 3,
        "reason": "recommendation",
    }
    assert names.index("answer_contract") < names.index(
        "card_display_contract"
    )
    assert names.index("card_display_contract") < names.index("products")
    assert (
        products["products"][0]["image_url"]
        == "/static/images/products/jd_v3_100222404954.png"
    )
    assert (
        products["products"][0]["detail_url"]
        == "https://item.jd.com/100222404954.html"
    )
    assert all(
        "match_score" not in item
        for item in products["products"]
    )
    assert products["cards"][0]["type"] == "product_card"
    message = next(data for name, data in events if name == "message")
    assert message["content"].strip()
    assert message["done"] is False


def test_frontend_product_projection_preserves_display_scope() -> None:
    product = _card_to_frontend_product(
        {
            "product_id": 33,
            "category_profile": "skincare",
            "category_facts": [],
            "variant_scope": "50ml正装",
            "specification": "50ml",
            "name": "雅诗兰黛特润修护肌活精华露50ml",
            "display_name": "雅诗兰黛特润修护肌活精华露",
            "brand": "雅诗兰黛",
            "category": "精华",
            "price": "968.0",
            "image_url": "/static/images/products/example.png",
            "detail_url": "https://example.invalid/product/33",
            "platform": "tmall",
            "image_source_sha256": None,
            "skin_match": "matched",
            "matched_efficacies": ["修护"],
            "fact_warnings": [],
        }
    )

    assert product["variant_scope"] == "50ml正装"
    assert product["specification"] == "50ml"
    assert product["display_name"] == "雅诗兰黛特润修护肌活精华露"
    assert product["name"] == "雅诗兰黛特润修护肌活精华露50ml"


def test_adapter_end_requires_explicit_idempotent_delivery_commit(
    real_reader,
    real_product_assets,
) -> None:
    class CountingConversationState(InMemoryConversationState):
        def __init__(self) -> None:
            super().__init__()
            self.save_calls = 0

        def save(self, snapshot, *, expected_version):
            self.save_calls += 1
            return super().save(
                snapshot,
                expected_version=expected_version,
            )

    state = CountingConversationState()
    orchestrator = compose_text_recommendation_orchestrator(
        real_reader,
        product_assets=real_product_assets,
        conversation_state=state,
    )

    events = list(
        iter_guide_public_events(
            orchestrator,
            _turn("500 元内敏感肌修护精华"),
        )
    )

    assert events[-1] == ("end", {"conversation_version": 1})
    assert state.save_calls == 0
    chat_api_adapter.commit_http_event_delivery(events[-1])
    chat_api_adapter.commit_http_event_delivery(events[-1])
    assert state.save_calls == 1
    assert state.load("s-1").version == 1


def test_clarification_code_is_persisted_from_typed_event_and_deferred(
) -> None:
    state = InMemoryConversationState()

    class ClarificationOrchestrator:
        _conversation_state = (
            chat_api_adapter.PublicEventCommitConversationState(state)
        )

        def stream(self, turn):
            yield StartEvent(data=StartData(session_id=turn.session_id))
            yield IntentEvent(data=IntentData(mode="clarify"))
            yield ClarifyEvent(
                data=ClarifyData(
                    question="预算必须大于 0",
                    clarification_code=ClarificationCode.BUDGET,
                )
            )
            yield EndEvent(
                data=EndData(
                    conversation_version=turn.conversation_version
                )
            )

    events = list(
        iter_guide_public_events(
            ClarificationOrchestrator(),
            _turn("0 元以内的防晒"),
        )
    )

    assert events[-1] == ("end", {"conversation_version": 1})
    assert state.load("s-1") is None

    chat_api_adapter.commit_http_event_delivery(events[-1])
    stored = state.load("s-1")
    assert stored is not None
    assert stored.clarification is not None
    assert stored.clarification.gap is ClarificationCode.BUDGET
    assert stored.clarification.attempts == 1


def test_new_public_clarification_copy_uses_typed_code() -> None:
    state = InMemoryConversationState()

    class OpenClarificationOrchestrator:
        _conversation_state = (
            chat_api_adapter.PublicEventCommitConversationState(state)
        )

        def stream(self, turn):
            yield StartEvent(data=StartData(session_id=turn.session_id))
            yield IntentEvent(data=IntentData(mode="clarify"))
            yield ClarifyEvent(
                data=ClarifyData(
                    question="任意开放语义追问",
                    clarification_code=ClarificationCode.CONCERN,
                )
            )
            yield EndEvent(
                data=EndData(
                    conversation_version=turn.conversation_version
                )
            )

    events = list(
        iter_guide_public_events(
            OpenClarificationOrchestrator(),
            _turn("帮我看看"),
        )
    )

    assert events[-1] == ("end", {"conversation_version": 1})
    chat_api_adapter.commit_http_event_delivery(events[-1])
    stored = state.load("s-1")
    assert stored is not None
    assert stored.clarification is not None
    assert stored.clarification.gap is ClarificationCode.CONCERN


def test_stale_typed_clarification_does_not_change_state() -> None:
    state = InMemoryConversationState()
    current = state.save(
        ConversationSnapshot(
            session_id="s-1",
            version=1,
            clarification=ClarificationProgress(
                gap=ClarificationCode.TOPIC,
                attempts=1,
            ),
        ),
        expected_version=0,
    )

    class OpenStaleClarificationOrchestrator:
        _conversation_state = (
            chat_api_adapter.PublicEventCommitConversationState(state)
        )

        def stream(self, turn):
            yield StartEvent(data=StartData(session_id=turn.session_id))
            yield IntentEvent(data=IntentData(mode="clarify"))
            yield ClarifyEvent(
                data=ClarifyData(
                    question="任意开放语义追问",
                    clarification_code=ClarificationCode.GOAL,
                )
            )
            yield EndEvent(
                data=EndData(
                    conversation_version=turn.conversation_version
                )
            )

    events = list(
        iter_guide_public_events(
            OpenStaleClarificationOrchestrator(),
            _turn("帮我看看"),
        )
    )

    assert events[-1] == ("end", {"conversation_version": 0})
    assert state.load("s-1") == current


def test_repair_serum_frontend_shape_contains_evidence(
    real_reader,
    real_product_assets,
) -> None:
    orchestrator = compose_text_recommendation_orchestrator(
        real_reader,
        product_assets=real_product_assets,
    )

    events = list(
        iter_guide_public_events(
            orchestrator,
            _turn("500 元内敏感肌修护精华"),
        )
    )

    products = next(data for name, data in events if name == "products")
    assert [item["id"] for item in products["products"]] == [38, 91]
    card_display = next(
        data
        for name, data in events
        if name == "card_display_contract"
    )
    assert card_display["visible_product_ids"] == [38, 91]
    assert card_display["max_cards"] == 2
    assert products["products"][0]["category"] == "精华"
    assert products["products"][0]["matched_efficacies"] == ["修护"]
    assert "已审核功效：修护" in (
        products["products"][0]["description"]
    )


def test_scenario_evidence_adapter_preserves_typed_wire_order(
    real_reader,
    real_product_assets,
) -> None:
    orchestrator = compose_text_recommendation_orchestrator(
        real_reader,
        product_assets=real_product_assets,
    )

    events = list(
        iter_guide_public_events(
            orchestrator,
            _turn("500 元内长时间户外防晒"),
        )
    )
    names = [name for name, _ in events]

    assert names.index("scenario_evidence") < names.index(
        "review_evidence"
    )
    assert names.index("review_evidence") < names.index("pitfalls")
    assert names.index("pitfalls") < names.index("decision_process")
    scenario = next(
        data for name, data in events if name == "scenario_evidence"
    )
    reviews = next(
        data for name, data in events if name == "review_evidence"
    )
    pitfalls = next(
        data for name, data in events if name == "pitfalls"
    )
    products = next(
        data for name, data in events if name == "products"
    )

    assert [item["product_id"] for item in scenario["records"]] == [
        101,
        101,
        101,
        26,
        26,
        26,
        52,
        52,
        52,
    ]
    assert reviews["approved_source_count"] == 6
    assert [
        item["product_id"] for item in reviews["results"]
    ] == [101, 26, 52]
    assert [
        len(item["evidence"]) for item in reviews["results"]
    ] == [0, 0, 0]
    assert all(
        item["verified_absence"]["kind"] == "verified_absence"
        for item in reviews["results"]
    )
    assert reviews["summaries"] == []
    assert pitfalls == {"pitfalls": []}
    assert [item["id"] for item in products["products"]] == [101, 26, 52]


def test_sensitive_scenario_adapter_retains_pitfall_evidence_refs(
    real_reader,
    real_product_assets,
) -> None:
    orchestrator = compose_text_recommendation_orchestrator(
        real_reader,
        product_assets=real_product_assets,
    )

    events = list(
        iter_guide_public_events(
            orchestrator,
            _turn("500 元内敏感期修护精华"),
        )
    )
    payload = next(
        data for name, data in events if name == "pitfalls"
    )

    assert [item["severity"] for item in payload["pitfalls"]] == [
        "medium",
        "medium",
    ]
    assert all(
        item["evidence_refs"]
        for item in payload["pitfalls"]
    )


def test_slice1_guide_clarify_is_visible_to_current_frontend(real_reader) -> None:
    orchestrator = compose_text_recommendation_orchestrator(real_reader)

    events = list(
        iter_guide_public_events(
            orchestrator,
            _turn("0 元以内的防晒"),
        )
    )

    names = [name for name, _ in events]
    assert "clarify" not in names
    message = next(data for name, data in events if name == "message")
    assert message["content"].strip()
    assert message["done"] is False
    assert names[-1] == "end"


def test_slice1_guide_error_event_is_frontend_compatible(
    broken_orchestrator,
) -> None:
    events = list(
        iter_guide_public_events(
            broken_orchestrator,
            _turn("500 内适合油敏肌的防晒"),
        )
    )

    assert events[-1][0] == "error"
    assert events[-1][1]["error"] == "GUIDE_INTERNAL_ERROR"
    assert "catalog failed" not in events[-1][1]["message"]
