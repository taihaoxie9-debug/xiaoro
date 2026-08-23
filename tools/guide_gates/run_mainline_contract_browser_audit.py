from __future__ import annotations

import argparse
from dataclasses import dataclass
from decimal import Decimal
import json
import os
from pathlib import Path
from typing import Any

from app.guide.intent.responsibility_matrix import Responsibility
from app.guide.presentation.contracts import CardDisplayContract, ProductCard
from app.guide.presentation.copywriter_contracts import (
    CopywriterTelemetry,
    DirectFactComponent,
    PresentationSection,
    deterministic_copy_source,
    successful_copy_provenance,
)
from app.guide.presentation.public_contracts import (
    ComparisonCell,
    ComparisonRow,
    PublicPresentationContract,
    WinnerPresentation,
)
from app.guide.retrieval.category_profiles import CategoryProfile
from app.guide.understanding.image_contracts import (
    IdentityEvidenceConsistency,
    IdentityState,
    ImageIdentityObservation,
    ObservationState,
    OcrObservationState,
    VisualObservationState,
)
from tools.guide_gates.attempt_ledger import (
    complete_attempt,
    consume_attempt_context,
    read_attempt_context,
)
from tools.guide_gates.build_task11_readiness import (
    verify_task11_readiness,
)


class AuditBundleError(ValueError):
    pass


class BoundedAuditFailure(AuditBundleError):
    def __init__(
        self,
        *,
        turn_id: str,
        owner: str,
        failure_code: str,
        evidence_directory: str | Path,
        message: str | None = None,
    ) -> None:
        super().__init__(message or failure_code)
        self.turn_id = turn_id
        self.owner = owner
        self.failure_code = failure_code
        self.evidence_directory = Path(evidence_directory)


class BoundedContractError(AuditBundleError):
    def __init__(
        self,
        *,
        owner: str,
        failure_code: str,
        message: str | None = None,
    ) -> None:
        super().__init__(message or failure_code)
        self.owner = owner
        self.failure_code = failure_code


ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True, slots=True)
class BoundedBrowserTurn:
    turn_id: str
    message: str
    expected_mode: str
    expected_recommendation_mode: str | None = None
    image_path: Path | None = None
    expected_image_product_id: int | None = None
    allow_clarification: bool = False


@dataclass(frozen=True, slots=True)
class BoundedBrowserTrajectory:
    trajectory_id: str
    turns: tuple[BoundedBrowserTurn, ...]


REQUIRED_TURN_FILES = frozenset({
    "request.json",
    "stream.sse",
    "presentation-contract.json",
    "terminal-dom.json",
    "screenshot.png",
    "console.json",
    "network.json",
})

FIXTURE_TURN_IDS = (
    "fixture-explore-recommendation",
    "fixture-fit-recommendation",
    "fixture-product-knowledge",
    "fixture-comparison",
    "fixture-image-identity",
    "fixture-image-fit-recommendation",
    "fixture-multi-image-comparison",
)

_FIXTURE_PRODUCTS = {
    38: {
        "name": "理肤泉新B5多效修护精华",
        "brand": "理肤泉",
        "price": Decimal("294"),
        "image_url": "/static/images/products/jd_v3_100160480140.png",
    },
    91: {
        "name": "玉泽皮肤屏障修护精华乳",
        "brand": "玉泽",
        "price": Decimal("88"),
        "image_url": "/static/images/products/jd_v3_10069603621835.png",
    },
}

VIEWPORTS = {
    "desktop": {"width": 1440, "height": 1000},
    "mobile": {"width": 390, "height": 844},
}

BOUNDED_TRAJECTORIES = (
    BoundedBrowserTrajectory(
        trajectory_id="bounded-text-fit",
        turns=(
            BoundedBrowserTurn(
                turn_id="t1",
                message=(
                    "给我推荐一款 900 到 1100 元的精华，"
                    "我是油敏肌，换季容易泛红"
                ),
                expected_mode="recommendation",
                expected_recommendation_mode="fit",
                allow_clarification=True,
            ),
        ),
    ),
    BoundedBrowserTrajectory(
        trajectory_id="bounded-text-context",
        turns=(
            BoundedBrowserTurn(
                turn_id="t1",
                message="给我推荐 900 到 1100 元的精华",
                expected_mode="recommendation",
                expected_recommendation_mode="explore",
            ),
            BoundedBrowserTurn(
                turn_id="t2",
                message="第二款的质地适合什么肤质？",
                expected_mode="product_knowledge",
            ),
            BoundedBrowserTurn(
                turn_id="t3",
                message=(
                    "我现在有点换季泛红，T 区出油，"
                    "我可能是什么肤质？"
                ),
                expected_mode="consultation",
            ),
            BoundedBrowserTurn(
                turn_id="t4",
                message="确认",
                expected_mode="consultation",
            ),
            BoundedBrowserTurn(
                turn_id="t5",
                message=(
                    "回到刚才的推荐，第一款和第二款"
                    "哪个更适合我的肤质？"
                ),
                expected_mode="comparison",
            ),
        ),
    ),
    BoundedBrowserTrajectory(
        trajectory_id="bounded-image-context",
        turns=(
            BoundedBrowserTurn(
                turn_id="t1",
                message="",
                expected_mode="image_identity",
                image_path=(
                    ROOT
                    / "tests/fixtures/guide/images/"
                    "product-38-index-control.png"
                ),
                expected_image_product_id=38,
            ),
            BoundedBrowserTurn(
                turn_id="t2",
                message=(
                    "给我找两款相似的，我最近换季泛红，"
                    "T 区出油。"
                ),
                expected_mode="recommendation",
                expected_recommendation_mode="explore",
            ),
            BoundedBrowserTurn(
                turn_id="t3",
                message=(
                    "图片里的 B5 和第一款哪个更适合我的肤质？"
                ),
                expected_mode="comparison",
            ),
        ),
    ),
)

_FETCH_CAPTURE = r"""
(() => {
    window.__mainlineAuditCaptures = [];
    window.__mainlineAuditCaptureErrors = [];
    const originalFetch = window.fetch.bind(window);
    window.fetch = async (...args) => {
        const response = await originalFetch(...args);
        const request = args[0];
        const options = args[1] || {};
        const url = typeof request === 'string'
            ? request
            : (request?.url || '');
        if (!url.includes('/api/v1/chat/stream')) return response;
        response.clone().arrayBuffer().then(buffer => {
            const bytes = Array.from(new Uint8Array(buffer));
            const raw = new TextDecoder('utf-8', {fatal: true}).decode(buffer);
            const events = raw.split(/\n\n+/).map(block => {
                let event = 'message';
                const data = [];
                for (const line of block.split('\n')) {
                    if (line.startsWith('event: ')) {
                        event = line.slice(7).trim();
                    } else if (line.startsWith('data: ')) {
                        data.push(line.slice(6));
                    }
                }
                if (!data.length) return null;
                return {event, data: JSON.parse(data.join('\n'))};
            }).filter(Boolean);
            window.__mainlineAuditCaptures.push({
                url,
                method: options.method || 'GET',
                body: typeof options.body === 'string' ? options.body : null,
                bytes,
                events
            });
        }).catch(error => {
            window.__mainlineAuditCaptureErrors.push(String(error));
        });
        return response;
    };
})()
"""


def required_public_text(
    sections: tuple[object, ...],
) -> tuple[str, ...]:
    output: list[str] = []
    for section in sections:
        if not isinstance(section, dict):
            continue
        for value in (
            section.get("copy_text"),
            section.get("advisor_reason"),
        ):
            if isinstance(value, str) and value:
                output.append(value)
        direct_facts = section.get("direct_facts", ())
        if not isinstance(direct_facts, (list, tuple)):
            continue
        output.extend(
            value
            for item in direct_facts
            if isinstance(item, dict)
            and isinstance(
                value := item.get("display_value"),
                str,
            )
            and value
        )
    return tuple(output)


def _normalize_visible_text(value: str) -> str:
    return " ".join(value.split())


def validate_bounded_contract(
    contract: dict[str, Any],
    *,
    expected_mode: str,
    expected_recommendation_mode: str | None,
    expected_image_product_id: int | None,
    observations: tuple[dict[str, Any], ...],
    allow_clarification: bool = False,
) -> None:
    """Reject production smoke output that falls back or changes its owner."""
    if contract.get("terminal_kind") == "clarification":
        if not allow_clarification:
            raise BoundedContractError(
                owner="planning_state",
                failure_code="unexpected_clarification",
                message="bounded smoke received unexpected clarification terminal",
            )
        clarification = contract.get("clarification")
        if (
            expected_mode != "recommendation"
            or expected_recommendation_mode != "fit"
            or not isinstance(clarification, dict)
            or clarification.get("intended_responsibility")
            != "recommendation"
            or clarification.get("intended_recommendation_mode") != "fit"
            or clarification.get("clarification_basis")
            != "fit_selection_evidence_gap"
            or clarification.get("fit_gap_stage")
            not in {
                "decision_selection",
                "public_fact_projection",
            }
            or clarification.get("fit_decision_status")
            not in {
                "SELECTED",
                "TIED_BY_BUSINESS_EVIDENCE",
                "INSUFFICIENT_FOR_WINNER",
                "NO_CANDIDATE",
            }
            or not isinstance(
                clarification.get("fit_candidate_count"),
                int,
            )
            or not isinstance(
                clarification.get("fit_evidence_ref_count"),
                int,
            )
            or not isinstance(
                clarification.get("fit_public_fact_count"),
                int,
            )
            or (
                clarification.get("fit_gap_stage")
                == "decision_selection"
                and clarification.get("fit_decision_status")
                == "SELECTED"
            )
            or (
                clarification.get("fit_gap_stage")
                == "public_fact_projection"
                and (
                    clarification.get("fit_decision_status")
                    != "SELECTED"
                    or clarification.get("fit_public_fact_count") != 0
                )
            )
        ):
            raise BoundedContractError(
                owner="planning_state",
                failure_code="invalid_fit_clarification",
                message="bounded smoke received invalid fit clarification",
            )
        return
    telemetry = contract.get("telemetry")
    if (
        not isinstance(telemetry, dict)
        or not successful_copy_provenance(
            copy_source=contract.get("copy_source"),
            fallback_reason=telemetry.get("fallback_reason"),
        )
    ):
        raise BoundedContractError(
            owner="presentation_provenance",
            failure_code="fallback_copy",
            message="bounded smoke forbids fallback copy",
        )
    if contract.get("mode") != expected_mode:
        raise BoundedContractError(
            owner="planning_state",
            failure_code="presentation_mode_mismatch",
        )
    if (
        expected_recommendation_mode is not None
        and contract.get("recommendation_mode")
        != expected_recommendation_mode
    ):
        raise BoundedContractError(
            owner="planning_state",
            failure_code="recommendation_mode_mismatch",
        )
    if expected_image_product_id is None:
        return
    if len(observations) != 1:
        raise BoundedContractError(
            owner="retrieval_identity",
            failure_code="image_identity_count_mismatch",
        )
    observation = observations[0]
    if (
        observation.get("identity_state") != "confirmed"
        or observation.get("confirmed_product_id")
        != expected_image_product_id
    ):
        raise BoundedContractError(
            owner="retrieval_identity",
            failure_code="image_identity_mismatch",
        )


def fixture_sse_bytes(turn_id: str) -> bytes:
    """Return one deterministic, fully typed zero-API terminal stream."""
    contract = _fixture_contract(turn_id)
    products = tuple(
        _fixture_card(product_id)
        for product_id in contract.visible_product_ids
    )
    intent, decision_status = _fixture_terminal_shape(turn_id)
    image_comparison_data = (
        _fixture_image_comparison_data()
        if turn_id == "fixture-multi-image-comparison"
        else None
    )
    answer_status = (
        decision_status
        if decision_status is not None
        else "NOT_APPLICABLE"
    )
    events: list[tuple[str, dict[str, Any]]] = [
        ("start", {"session_id": turn_id}),
        (
            "intent",
            {
                "intent": intent,
                "entities": {},
                "scenario_intent": intent,
                "guide": True,
            },
        ),
        (
            "answer_contract",
            {
                "answer_contract": {
                    "product_count": len(products),
                    "winner_status": answer_status,
                    "has_unknown_skin": False,
                },
                "product_count": len(products),
                "winner_status": answer_status,
                "has_unknown_skin": False,
            },
        ),
        (
            "card_display_contract",
            contract.card_display.model_dump(mode="json"),
        ),
        (
            "products",
            {
                "cards": [
                    card.model_dump(mode="json")
                    for card in products
                ],
                "products": [
                    _frontend_product(card)
                    for card in products
                ],
            },
        ),
    ]
    if turn_id == "fixture-multi-image-comparison":
        events.extend(
            (
                (
                    "image_observation",
                    {
                        "observation": _fixture_image_observation(
                            image_ordinal=1,
                            product_id=38,
                            alternate_product_id=91,
                        )
                    },
                ),
                (
                    "image_observation",
                    {
                        "observation": _fixture_image_observation(
                            image_ordinal=2,
                            product_id=91,
                            alternate_product_id=38,
                        )
                    },
                ),
            )
        )
    if decision_status is not None:
        step_data = {
            "winner_status": decision_status,
            "products": len(products),
        }
        if image_comparison_data is not None:
            step_data["outcome"] = image_comparison_data
        decision_data: dict[str, Any] = {
            "ordered_product_ids": list(
                contract.visible_product_ids
            ),
            "winner_status": decision_status,
            "evidence_refs": [],
            "decision_process": {
                "steps": [
                    {
                        "type": "decision",
                        "title": "执行后端筛选规则",
                        "description": "已按公开展示合同完成筛选。",
                        "data": step_data,
                    }
                ],
                "final_recommendation": None,
            },
        }
        if image_comparison_data is not None:
            decision_data["comparison_data"] = (
                image_comparison_data
            )
        events.append(
            (
                "decision_process",
                decision_data,
            )
        )
    events.extend(
        (
            (
                "presentation_contract",
                contract.model_dump(mode="json"),
            ),
            ("end", {"conversation_version": 1}),
        )
    )
    return b"".join(
        (
            f"event: {event}\n"
            f"data: {json.dumps(data, ensure_ascii=False, separators=(',', ':'))}\n\n"
        ).encode("utf-8")
        for event, data in events
    )


def _fixture_terminal_shape(
    turn_id: str,
) -> tuple[str, str | None]:
    mapping = {
        "fixture-explore-recommendation": (
            "recommend",
            "INSUFFICIENT_FOR_WINNER",
        ),
        "fixture-fit-recommendation": ("recommend", "SELECTED"),
        "fixture-product-knowledge": ("knowledge", None),
        "fixture-comparison": ("comparison", "SELECTED"),
        "fixture-image-identity": ("image_identity", None),
        "fixture-image-fit-recommendation": (
            "image_recommend",
            "SELECTED",
        ),
        "fixture-multi-image-comparison": (
            "image_compare",
            "winner",
        ),
    }
    try:
        return mapping[turn_id]
    except KeyError as error:
        raise ValueError(f"unknown fixture turn: {turn_id}") from error


def _fixture_contract(turn_id: str) -> PublicPresentationContract:
    telemetry = CopywriterTelemetry(
        provider="fixture",
        model="deterministic",
        prompt_tokens=0,
        completion_tokens=0,
        total_tokens=0,
        latency_ms=0.0,
        fallback_reason=None,
    )
    if turn_id == "fixture-explore-recommendation":
        return _recommendation_contract(
            product_ids=(38, 91),
            fit=False,
            telemetry=telemetry,
        )
    if turn_id == "fixture-fit-recommendation":
        return _recommendation_contract(
            product_ids=(38,),
            fit=True,
            telemetry=telemetry,
        )
    if turn_id == "fixture-image-fit-recommendation":
        return _recommendation_contract(
            product_ids=(91,),
            fit=True,
            telemetry=telemetry,
        )
    if turn_id == "fixture-product-knowledge":
        return PublicPresentationContract(
            responsibility=Responsibility.PRODUCT_KNOWLEDGE,
            mode="product_knowledge",
            copy_source=_fixture_copy_source("product_knowledge"),
            sections=(
                PresentationSection(
                    kind="summary",
                    copy_text="我按你问的内容整理这款商品的相关信息。",
                ),
                PresentationSection(
                    kind="answer",
                    copy_text="品牌主打修护舒缓的使用方向。",
                    used_fact_ids=("fixture:38:brand_main",),
                ),
                PresentationSection(kind="full_cards"),
            ),
            visible_product_ids=(38,),
            card_display=_card_display("single", (38,)),
            telemetry=telemetry,
        )
    if turn_id == "fixture-image-identity":
        return PublicPresentationContract(
            responsibility=Responsibility.IMAGE_IDENTITY,
            mode="image_identity",
            copy_source=_fixture_copy_source("image_identity"),
            sections=(
                PresentationSection(
                    kind="observation",
                    copy_text="图片中的商品已确认，下面只展示已核对信息。",
                ),
                PresentationSection(
                    kind="product",
                    slot_id="p1",
                    product_id=38,
                    direct_facts=(
                        DirectFactComponent(
                            fact_id="fixture:38:brand_main",
                            label="品牌主打",
                            display_value="修护舒缓",
                        ),
                    ),
                ),
                PresentationSection(kind="full_cards"),
            ),
            visible_product_ids=(38,),
            card_display=_card_display("single", (38,)),
            telemetry=telemetry,
        )
    if turn_id == "fixture-comparison":
        return _comparison_contract(telemetry=telemetry)
    if turn_id == "fixture-multi-image-comparison":
        return _comparison_contract(telemetry=telemetry)
    raise ValueError(f"unknown fixture turn: {turn_id}")


def _recommendation_contract(
    *,
    product_ids: tuple[int, ...],
    fit: bool,
    telemetry: CopywriterTelemetry,
) -> PublicPresentationContract:
    sections: list[PresentationSection] = [
        PresentationSection(
            kind="summary",
            copy_text="先按修护方向和使用感受看这几款的差异。",
        )
    ]
    for index, product_id in enumerate(product_ids, start=1):
        sections.append(
            PresentationSection(
                kind="product",
                copy_text="品牌主打修护舒缓的使用方向。",
                used_fact_ids=(
                    f"fixture:{product_id}:brand_main",
                ),
                advisor_reason="更适合优先关注舒缓的人。",
                advisor_used_fact_ids=(
                    f"fixture:{product_id}:brand_main",
                ),
                slot_id=f"p{index}",
                product_id=product_id,
                direct_facts=(
                    DirectFactComponent(
                        fact_id=f"fixture:{product_id}:brand_main",
                        label="品牌主打",
                        display_value="修护舒缓",
                    ),
                ),
            )
        )
    if fit:
        product_id = product_ids[0]
        winner = WinnerPresentation(
            status="selected",
            winner_product_id=product_id,
            reason="综合当前需求，修护舒缓方向更贴合。",
            fact_ids=(f"fixture:{product_id}:brand_main",),
            dimension_ids=("brand_main",),
        )
        closing = PresentationSection(kind="closing")
        recommendation_mode = "fit"
    else:
        winner = WinnerPresentation(status="not_applicable")
        closing = PresentationSection(
            kind="closing",
            copy_text="可以再按当前最在意的一项继续收窄。",
        )
        recommendation_mode = "explore"
    sections.extend((closing, PresentationSection(kind="full_cards")))
    return PublicPresentationContract(
        responsibility=Responsibility.RECOMMENDATION,
        mode="recommendation",
        recommendation_mode=recommendation_mode,
        copy_source=_fixture_copy_source("recommendation"),
        sections=tuple(sections),
        winner=winner,
        visible_product_ids=product_ids,
        card_display=_card_display(
            "single" if len(product_ids) == 1 else "recommendation",
            product_ids,
        ),
        telemetry=telemetry,
    )


def _comparison_contract(
    *,
    telemetry: CopywriterTelemetry,
) -> PublicPresentationContract:
    product_ids = (38, 91)
    rows = (
        ComparisonRow(
            dimension_id="brand_main",
            label="品牌主打",
            cells=tuple(
                ComparisonCell(
                    product_id=product_id,
                    value="修护舒缓",
                    fact_ids=(f"fixture:{product_id}:brand_main",),
                    state="known",
                )
                for product_id in product_ids
            ),
        ),
        ComparisonRow(
            dimension_id="texture.refreshing",
            label="清爽肤感",
            cells=tuple(
                ComparisonCell(
                    product_id=product_id,
                    value="轻薄好吸收",
                    fact_ids=(f"fixture:{product_id}:texture",),
                    state="known",
                )
                for product_id in product_ids
            ),
        ),
        ComparisonRow(
            dimension_id="profile_match",
            label="当前画像匹配",
            cells=tuple(
                ComparisonCell(
                    product_id=product_id,
                    value="当前需求匹配",
                    fact_ids=(f"fixture:{product_id}:profile",),
                    state="known",
                )
                for product_id in product_ids
            ),
        ),
    )
    return PublicPresentationContract(
        responsibility=Responsibility.COMPARISON,
        mode="comparison",
        copy_source=_fixture_copy_source("comparison"),
        sections=(
            PresentationSection(
                kind="summary",
                copy_text="这两款的重点不同，直接看当前问题相关的差异。",
            ),
            PresentationSection(kind="comparison"),
            PresentationSection(kind="full_cards"),
        ),
        requested_comparison_dimensions=("texture.refreshing",),
        comparison_rows=rows,
        winner=WinnerPresentation(
            status="selected",
            winner_product_id=38,
            reason="综合当前对比维度，修护舒缓方向更贴合。",
            fact_ids=(
                "fixture:38:brand_main",
                "fixture:38:texture",
                "fixture:38:profile",
            ),
            dimension_ids=(
                "brand_main",
                "texture.refreshing",
                "profile_match",
            ),
        ),
        visible_product_ids=product_ids,
        card_display=_card_display("comparison", product_ids),
        telemetry=telemetry,
    )


def _fixture_copy_source(mode: str) -> str:
    source = deterministic_copy_source(
        mode=mode,
        copywriter_policy="eligible",
        has_authoritative_public_copy=True,
    )
    if source is None:
        raise AssertionError("fixture copy source must be deterministic")
    return source


def _fixture_card(product_id: int) -> ProductCard:
    source = _FIXTURE_PRODUCTS[product_id]
    return ProductCard(
        product_id=product_id,
        category_profile=CategoryProfile.SKINCARE,
        category_facts=(),
        specification="30ml",
        display_name=source["name"],
        name=source["name"],
        brand=source["brand"],
        category="精华",
        price=source["price"],
        image_url=source["image_url"],
        detail_url=f"/api/v1/search/products/{product_id}",
        platform="fixture",
        skin_match="unknown",
        matched_efficacies=[],
        fact_warnings=[],
    )


def _fixture_image_observation(
    *,
    image_ordinal: int,
    product_id: int,
    alternate_product_id: int,
) -> dict[str, Any]:
    return ImageIdentityObservation(
        image_id=f"image_{image_ordinal}{'f' * 32}",
        observation_state=ObservationState.PARTIAL,
        visual_state=VisualObservationState.OBSERVED,
        ocr_state=OcrObservationState.NOT_CONFIGURED,
        identity_state=IdentityState.CONFIRMED,
        confirmed_product_id=product_id,
        candidate_product_ids=(product_id, alternate_product_id),
        visual_confidence=0.99,
        similarity_margin=0.2,
        model_name="fixture-openclip",
        weights_sha256="a" * 64,
        preprocessing_version="fixture-preprocess-v1",
        vector_dimension=512,
        index_sha256="b" * 64,
        ocr_brand_consistency=IdentityEvidenceConsistency.NOT_CHECKED,
        ocr_product_name_consistency=(
            IdentityEvidenceConsistency.NOT_CHECKED
        ),
    ).model_dump(mode="json")


def _fixture_image_comparison_data() -> dict[str, Any]:
    references = [
        {
            "ordinal": 1,
            "image_id": f"image_1{'f' * 32}",
            "product_id": 38,
        },
        {
            "ordinal": 2,
            "image_id": f"image_2{'f' * 32}",
            "product_id": 91,
        },
    ]
    return {
        "status": "winner",
        "references": references,
        "winner_reference": references[0],
        "tie_reason": None,
        "comparison_dimensions": ["price"],
        "evidence_refs": [],
        "evaluated_price_facts": [
            {
                "reference": references[0],
                "state": "known",
                "value": "294",
                "source_refs": [],
            },
            {
                "reference": references[1],
                "state": "known",
                "value": "88",
                "source_refs": [],
            },
        ],
    }


def _frontend_product(card: ProductCard) -> dict[str, Any]:
    payload = card.model_dump(mode="json")
    return {
        "id": payload["product_id"],
        "product_id": payload["product_id"],
        "category_profile": payload["category_profile"],
        "category_facts": payload["category_facts"],
        "variant_scope": payload["variant_scope"],
        "price_specification_alignment": (
            payload["price_specification_alignment"]
        ),
        "specification": payload["specification"],
        "name": payload["name"],
        "display_name": payload["display_name"],
        "brand": payload["brand"],
        "category": payload["category"],
        "price": payload["price"],
        "image_url": payload["image_url"],
        "detail_url": payload["detail_url"],
        "platform": payload["platform"],
        "image_source_sha256": payload["image_source_sha256"],
        "description": "当前卡片只展示已核对信息。",
        "efficacy_match": "not_applicable",
        "matched_efficacies": [],
        "suitable_skin": "以已核对信息为准",
        "fact_warnings": [],
    }


def _card_display(
    mode: str,
    product_ids: tuple[int, ...],
) -> CardDisplayContract:
    return CardDisplayContract(
        mode=mode,
        visible_product_ids=product_ids,
        max_cards=len(product_ids),
        reason=(
            "comparison"
            if mode == "comparison"
            else (
                "product"
                if mode == "single"
                else "recommendation"
            )
        ),
    )


def run_fixture_browser_audit(
    *,
    base_url: str,
    output: Path,
    viewport: str = "desktop",
) -> dict[str, Any]:
    """Render all six typed fixture streams through the actual chat reducer."""
    if viewport not in VIEWPORTS:
        raise ValueError("fixture audit requires a concrete viewport")
    from playwright.sync_api import sync_playwright

    output.mkdir(parents=True, exist_ok=False)
    report: dict[str, Any] = {
        "schema_version": "guide-mainline-contract-browser-audit-v1",
        "trajectory_set": "fixture",
        "base_url": base_url,
        "viewport": viewport,
        "turns": [],
        "invalid_clarification_count": 0,
    }
    executable = os.environ.get(
        "PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH"
    )
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            executable_path=executable or None,
        )
        try:
            for turn_id in FIXTURE_TURN_IDS:
                turn_dir = output / turn_id
                turn_dir.mkdir()
                context = browser.new_context(viewport=VIEWPORTS[viewport])
                page = context.new_page()
                _install_fixture_route(
                    page,
                    stream=fixture_sse_bytes(turn_id),
                )
                evidence = _browser_evidence(page)
                page.add_init_script(_FETCH_CAPTURE)
                page.goto(f"{base_url.rstrip('/')}/chat")
                page.fill("#chatInput", f"fixture:{turn_id}")
                page.click("#sendBtn")
                _wait_for_fixture_terminal(page)
                _write_fixture_turn_bundle(
                    page=page,
                    turn_dir=turn_dir,
                    turn_id=turn_id,
                    viewport=viewport,
                    evidence=evidence,
                )
                validate_audit_bundle(
                    turn_dir,
                    expected_turn_id=turn_id,
                )
                report["turns"].append({
                    "turn_id": turn_id,
                    "directory": turn_dir.name,
                })
                context.close()
        finally:
            browser.close()
    report["turn_count"] = len(report["turns"])
    report["passed"] = report["turn_count"] == len(FIXTURE_TURN_IDS)
    _write_json(output / "summary.json", report)
    return report


def run_fixture_browser_audits(
    *,
    base_url: str,
    output: Path,
    viewport: str,
) -> dict[str, Any]:
    """Run one fixture audit or the desktop and mobile evidence pair."""
    if viewport in VIEWPORTS:
        return run_fixture_browser_audit(
            base_url=base_url,
            output=output,
            viewport=viewport,
        )
    if viewport != "all":
        raise ValueError("fixture audit viewport is invalid")

    output.mkdir(parents=True, exist_ok=False)
    reports: dict[str, dict[str, Any]] = {}
    for viewport_name in VIEWPORTS:
        reports[viewport_name] = run_fixture_browser_audit(
            base_url=base_url,
            output=output / viewport_name,
            viewport=viewport_name,
        )
    report: dict[str, Any] = {
        "schema_version": "guide-mainline-contract-browser-audit-v1",
        "trajectory_set": "fixture",
        "base_url": base_url,
        "viewport": "all",
        "reports": reports,
        "turn_count": sum(
            item["turn_count"] for item in reports.values()
        ),
        "invalid_clarification_count": sum(
            int(item.get("invalid_clarification_count", 0))
            for item in reports.values()
        ),
        "passed": all(
            item["passed"] for item in reports.values()
        ),
    }
    _write_json(output / "summary.json", report)
    return report


def run_bounded_browser_audit(
    *,
    base_url: str,
    output: Path,
    viewport: str,
) -> dict[str, Any]:
    """Run the fixed paid smoke once and stop on its first failed turn."""
    if viewport not in VIEWPORTS:
        raise ValueError(
            "bounded smoke requires one concrete viewport"
        )
    from playwright.sync_api import sync_playwright

    output.mkdir(parents=True, exist_ok=False)
    report: dict[str, Any] = {
        "schema_version": "guide-mainline-contract-browser-audit-v1",
        "trajectory_set": "bounded",
        "base_url": base_url,
        "viewport": viewport,
        "trajectories": [],
        "turn_count": 0,
        "invalid_clarification_count": 0,
        "passed": False,
    }
    _write_json(output / "summary.json", report)
    executable = os.environ.get(
        "PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH"
    )
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            executable_path=executable or None,
        )
        try:
            for trajectory in BOUNDED_TRAJECTORIES:
                try:
                    trajectory_report = _run_bounded_browser_trajectory(
                        browser=browser,
                        base_url=base_url,
                        output=output,
                        trajectory=trajectory,
                        viewport=viewport,
                    )
                except AuditBundleError as error:
                    summary_path = (
                        output
                        / trajectory.trajectory_id
                        / "summary.json"
                    )
                    if summary_path.is_file():
                        failed_report = json.loads(
                            summary_path.read_text(encoding="utf-8")
                        )
                        report["trajectories"].append(failed_report)
                        report["turn_count"] += failed_report["turn_count"]
                        report["invalid_clarification_count"] += (
                            failed_report[
                                "invalid_clarification_count"
                            ]
                        )
                        _write_json(output / "summary.json", report)
                    completed_turns = int(
                        failed_report.get("turn_count", 0)
                    ) if summary_path.is_file() else 0
                    failed_turn = trajectory.turns[
                        min(completed_turns, len(trajectory.turns) - 1)
                    ]
                    evidence_directory = (
                        output
                        / trajectory.trajectory_id
                        / failed_turn.turn_id
                    )
                    raise BoundedAuditFailure(
                        turn_id=(
                            f"{trajectory.trajectory_id}-"
                            f"{failed_turn.turn_id}"
                        ),
                        owner=(
                            error.owner
                            if isinstance(error, BoundedContractError)
                            else _failure_owner_from_bundle(
                                evidence_directory
                            )
                        ),
                        failure_code=(
                            error.failure_code
                            if isinstance(error, BoundedContractError)
                            else type(error).__name__
                        ),
                        evidence_directory=evidence_directory,
                        message=str(error),
                    ) from error
                report["trajectories"].append(trajectory_report)
                report["turn_count"] += trajectory_report["turn_count"]
                report["invalid_clarification_count"] += (
                    trajectory_report["invalid_clarification_count"]
                )
                _write_json(output / "summary.json", report)
        finally:
            browser.close()
    report["passed"] = (
        len(report["trajectories"]) == len(BOUNDED_TRAJECTORIES)
        and report["turn_count"]
        == sum(
            len(trajectory.turns)
            for trajectory in BOUNDED_TRAJECTORIES
        )
    )
    _write_json(output / "summary.json", report)
    return report


def _failure_owner_from_bundle(turn_dir: Path) -> str:
    contract_path = turn_dir / "presentation-contract.json"
    if not contract_path.is_file():
        return "sse_contract"
    try:
        contract = _read_object(contract_path)
    except AuditBundleError:
        return "sse_contract"
    if contract.get("terminal_kind") == "error":
        return "sse_contract"
    if contract.get("terminal_kind") == "clarification":
        return "planning_state"
    if contract.get("copy_source") == "fallback":
        return "presentation_provenance"
    if (turn_dir / "terminal-dom.json").is_file():
        return "dom_rendering"
    return "sse_contract"


def run_authorized_bounded_browser_audit(
    *,
    base_url: str,
    attempt_context: str | Path,
    viewport: str,
) -> dict[str, Any]:
    context_path = Path(attempt_context)
    raw_context = _read_object(context_path)
    ledger_path = Path(str(raw_context.get("ledger_path")))
    readiness_path = Path(str(raw_context.get("readiness_path")))
    context = read_attempt_context(
        context_path,
        ledger_path=ledger_path,
        readiness_path=readiness_path,
    )
    verify_task11_readiness(
        readiness_path=readiness_path,
        ledger_path=ledger_path,
    )
    consume_attempt_context(
        context_path,
        phase="bounded",
        ledger_path=ledger_path,
        readiness_path=readiness_path,
    )
    output = Path(str(context["output_directory"])) / (
        f"browser-{viewport}"
    )
    try:
        report = run_bounded_browser_audit(
            base_url=base_url,
            output=output,
            viewport=viewport,
        )
        if (
            report.get("passed") is not True
            or report.get("invalid_clarification_count") != 0
        ):
            raise AuditBundleError(
                "bounded smoke result failed"
            )
    except BoundedAuditFailure as error:
        complete_attempt(
            context_path,
            result="failed",
            first_failure_turn_id=error.turn_id,
            first_failure_owner=error.owner,
            failure_code=error.failure_code,
            evidence_directory=str(error.evidence_directory),
        )
        raise
    except BaseException as error:
        complete_attempt(
            context_path,
            result="failed",
            first_failure_turn_id="bounded-runner-startup",
            first_failure_owner="browser_audit",
            failure_code=type(error).__name__,
            evidence_directory=str(output),
        )
        raise
    complete_attempt(context_path, result="passed")
    return report


def resolve_cli_output(
    *,
    trajectory_set: str,
    output: Path | None,
    attempt_context: Path | None,
) -> Path:
    if trajectory_set == "fixture":
        if output is None:
            raise AuditBundleError("fixture requires --output")
        if attempt_context is not None:
            raise AuditBundleError(
                "fixture forbids --attempt-context"
            )
        return output
    if attempt_context is None:
        raise AuditBundleError(
            f"{trajectory_set} requires --attempt-context"
        )
    if output is not None:
        raise AuditBundleError(
            f"{trajectory_set} forbids --output"
        )
    return attempt_context


def _run_bounded_browser_trajectory(
    *,
    browser,
    base_url: str,
    output: Path,
    trajectory: BoundedBrowserTrajectory,
    viewport: str,
) -> dict[str, Any]:
    trajectory_dir = output / trajectory.trajectory_id
    trajectory_dir.mkdir()
    context = browser.new_context(viewport=VIEWPORTS[viewport])
    page = context.new_page()
    _install_icon_route(page)
    page.add_init_script(_FETCH_CAPTURE)
    evidence = _browser_evidence(page)
    page.goto(f"{base_url.rstrip('/')}/chat")
    report: dict[str, Any] = {
        "trajectory_id": trajectory.trajectory_id,
        "turns": [],
        "turn_count": 0,
        "invalid_clarification_count": 0,
    }
    _write_json(trajectory_dir / "summary.json", report)
    try:
        for turn in trajectory.turns:
            turn_dir = trajectory_dir / turn.turn_id
            turn_dir.mkdir()
            capture_count = _capture_count(page)
            evidence_offsets = {
                name: len(items)
                for name, items in evidence.items()
            }
            if turn.image_path is not None:
                if not turn.image_path.is_file():
                    raise AuditBundleError(
                        "bounded smoke image fixture is missing"
                    )
                page.set_input_files(
                    "#imageInput",
                    str(turn.image_path),
                )
                page.wait_for_function(
                    """() => (
                        document.querySelectorAll(
                            '#imagePreview .preview-item'
                        ).length === 1
                    )""",
                    timeout=10_000,
                )
            if turn.message:
                page.fill("#chatInput", turn.message)
            page.click("#sendBtn")
            _wait_for_live_terminal(
                page,
                expected_capture_count=capture_count + 1,
            )
            turn_evidence = {
                name: items[evidence_offsets[name]:]
                for name, items in evidence.items()
            }
            contract, observations = _write_live_turn_bundle(
                page=page,
                turn_dir=turn_dir,
                trajectory_id=trajectory.trajectory_id,
                turn=turn,
                viewport=viewport,
                capture_index=capture_count,
                evidence=turn_evidence,
            )
            validate_audit_bundle(
                turn_dir,
                expected_turn_id=(
                    f"{trajectory.trajectory_id}-{turn.turn_id}"
                ),
            )
            try:
                validate_bounded_contract(
                    contract,
                    expected_mode=turn.expected_mode,
                    expected_recommendation_mode=(
                        turn.expected_recommendation_mode
                    ),
                    expected_image_product_id=(
                        turn.expected_image_product_id
                    ),
                    observations=observations,
                    allow_clarification=turn.allow_clarification,
                )
            except AuditBundleError:
                if contract.get("terminal_kind") == "clarification":
                    report["invalid_clarification_count"] += 1
                    _write_json(
                        trajectory_dir / "summary.json",
                        report,
                    )
                raise
            if turn_evidence["console"] or turn_evidence["network"]:
                raise AuditBundleError(
                    "bounded smoke browser telemetry failure"
                )
            report["turns"].append({
                "turn_id": turn.turn_id,
                "directory": str(
                    turn_dir.relative_to(output)
                ),
            })
            report["turn_count"] += 1
            _write_json(trajectory_dir / "summary.json", report)
    finally:
        context.close()
    return report


def _install_icon_route(page) -> None:
    page.route(
        "https://unpkg.com/**",
        lambda route: route.fulfill(
            status=200,
            content_type="application/javascript",
            body="window.feather={replace:function(){}};",
        ),
    )


def _capture_count(page) -> int:
    count = page.evaluate(
        "() => window.__mainlineAuditCaptures.length"
    )
    if not isinstance(count, int) or isinstance(count, bool):
        raise AuditBundleError("browser capture count is invalid")
    return count


def _wait_for_live_terminal(
    page,
    *,
    expected_capture_count: int,
) -> None:
    page.wait_for_function(
        """expected => (
            window.__mainlineAuditCaptures.length >= expected
            && window.__mainlineAuditCaptureErrors.length === 0
            && typeof activeChatRequests !== 'undefined'
            && activeChatRequests.size === 0
        )""",
        arg=expected_capture_count,
        timeout=120_000,
    )
    capture_errors = page.evaluate(
        "() => window.__mainlineAuditCaptureErrors"
    )
    if not isinstance(capture_errors, list) or capture_errors:
        raise AuditBundleError("browser SSE capture failed")


def _write_live_turn_bundle(
    *,
    page,
    turn_dir: Path,
    trajectory_id: str,
    turn: BoundedBrowserTurn,
    viewport: str,
    capture_index: int,
    evidence: dict[str, list[dict[str, str]]],
) -> tuple[dict[str, Any], tuple[dict[str, Any], ...]]:
    capture = page.evaluate(
        """index => window.__mainlineAuditCaptures[index] || null""",
        capture_index,
    )
    if not isinstance(capture, dict):
        raise AuditBundleError("browser capture is unavailable")
    raw_bytes = capture.get("bytes")
    if (
        not isinstance(raw_bytes, list)
        or any(
            not isinstance(value, int)
            or isinstance(value, bool)
            or value < 0
            or value > 255
            for value in raw_bytes
        )
    ):
        raise AuditBundleError("browser capture bytes are invalid")
    events = capture.get("events")
    if not isinstance(events, list):
        raise AuditBundleError("browser capture events are invalid")
    request_id = page.evaluate(
        """() => {
            const wrappers = Array.from(document.querySelectorAll(
                '.message-wrapper.ai[data-guide-request-id]'
            ));
            return wrappers.at(-1)?.dataset.guideRequestId || null;
        }"""
    )
    if not isinstance(request_id, str) or not request_id:
        request_id = None
    request_body = capture.get("body")
    try:
        parsed_body = (
            json.loads(request_body)
            if isinstance(request_body, str)
            else None
        )
    except json.JSONDecodeError as error:
        raise AuditBundleError("browser request JSON is invalid") from error
    if not isinstance(parsed_body, dict):
        raise AuditBundleError("browser request body is unavailable")

    _write_json(
        turn_dir / "request.json",
        {
            "turn_id": f"{trajectory_id}-{turn.turn_id}",
            "request_id": request_id,
            "viewport": VIEWPORTS[viewport],
            "method": capture.get("method"),
            "url": capture.get("url"),
            "user_message": turn.message,
            "request_message": parsed_body.get("message"),
            "body": parsed_body,
        },
    )
    (turn_dir / "stream.sse").write_bytes(bytes(raw_bytes))
    try:
        terminal_kind, terminal = _terminal_from_capture_events(events)
    except AuditBundleError:
        _write_json(
            turn_dir / "presentation-contract.json",
            {"audit_error": "missing_presentation_contract"},
        )
        _write_json(
            turn_dir / "terminal-dom.json",
            _failed_terminal_dom(request_id),
        )
        _write_json(turn_dir / "console.json", evidence["console"])
        _write_json(turn_dir / "network.json", evidence["network"])
        page.screenshot(
            path=str(turn_dir / "screenshot.png"),
            full_page=True,
        )
        raise AuditBundleError(
            "browser capture must contain one typed terminal"
        )
    _write_json(turn_dir / "presentation-contract.json", terminal)
    if terminal_kind == "error":
        _write_json(
            turn_dir / "terminal-dom.json",
            _failed_terminal_dom(
                request_id,
                terminal_kind="error",
            ),
        )
        _write_json(turn_dir / "console.json", evidence["console"])
        _write_json(turn_dir / "network.json", evidence["network"])
        page.screenshot(
            path=str(turn_dir / "screenshot.png"),
            full_page=True,
        )
        error_data = terminal["error"]
        raise BoundedContractError(
            owner="sse_contract",
            failure_code=error_data["error"],
            message=error_data["error"],
        )
    if request_id is None:
        _write_json(
            turn_dir / "terminal-dom.json",
            _failed_terminal_dom(request_id),
        )
        _write_json(turn_dir / "console.json", evidence["console"])
        _write_json(turn_dir / "network.json", evidence["network"])
        page.screenshot(
            path=str(turn_dir / "screenshot.png"),
            full_page=True,
        )
        raise AuditBundleError("browser request ID is unavailable")
    _write_json(
        turn_dir / "terminal-dom.json",
        _terminal_dom(
            page,
            request_id=request_id,
            terminal_kind=terminal_kind,
        ),
    )
    _write_json(turn_dir / "console.json", evidence["console"])
    _write_json(turn_dir / "network.json", evidence["network"])
    page.screenshot(
        path=str(turn_dir / "screenshot.png"),
        full_page=True,
    )
    observations = tuple(
        event.get("data", {}).get("observation")
        for event in events
        if (
            isinstance(event, dict)
            and event.get("event") == "image_observation"
            and isinstance(event.get("data"), dict)
            and isinstance(
                event["data"].get("observation"),
                dict,
            )
        )
    )
    return terminal, observations


def _terminal_from_capture_events(
    events: list[object],
) -> tuple[str, dict[str, Any]]:
    presentations = tuple(
        event.get("data")
        for event in events
        if (
            isinstance(event, dict)
            and event.get("event") == "presentation_contract"
            and isinstance(event.get("data"), dict)
        )
    )
    clarifications = tuple(
        event.get("data")
        for event in events
        if (
            isinstance(event, dict)
            and event.get("event") == "clarify"
            and isinstance(event.get("data"), dict)
        )
    )
    errors = tuple(
        event.get("data")
        for event in events
        if (
            isinstance(event, dict)
            and event.get("event") == "error"
            and isinstance(event.get("data"), dict)
        )
    )
    if len(presentations) == 1 and not clarifications and not errors:
        return "presentation", presentations[0]
    if len(clarifications) == 1 and not presentations and not errors:
        clarification = clarifications[0]
        question = clarification.get("question")
        code = clarification.get("clarification_code")
        if (
            not isinstance(question, str)
            or not question
            or not isinstance(code, str)
            or not code
        ):
            raise AuditBundleError("clarification terminal is invalid")
        return (
            "clarification",
            {
                "terminal_kind": "clarification",
                "clarification": clarification,
            },
        )
    if len(errors) == 1 and not presentations and not clarifications:
        error = errors[0]
        code = error.get("error")
        message = error.get("message")
        if (
            not isinstance(code, str)
            or not code
            or (
                message is not None
                and not isinstance(message, str)
            )
        ):
            raise AuditBundleError("error terminal is invalid")
        return (
            "error",
            {
                "terminal_kind": "error",
                "error": error,
            },
        )
    raise AuditBundleError("browser capture must contain one typed terminal")


def _failed_terminal_dom(
    request_id: str | None,
    *,
    terminal_kind: str | None = None,
) -> dict[str, Any]:
    return {
        "request_id": request_id,
        "terminal_kind": terminal_kind,
        "presentation_mode": None,
        "legacy_message_count": 0,
        "legacy_product_card_count": 0,
        "turn_presentation_root_count": 0,
        "visible_section_kinds": [],
        "inline_product_ids": [],
        "visible_product_ids": [],
        "shelf_product_ids": [],
        "presentation_text": "",
    }


def _install_fixture_route(
    page,
    *,
    stream: bytes,
) -> None:
    _install_icon_route(page)
    page.route(
        "**/api/v1/chat/stream",
        lambda route: route.fulfill(
            status=200,
            content_type="text/event-stream; charset=utf-8",
            body=stream,
        ),
    )


def _browser_evidence(page) -> dict[str, list[dict[str, str]]]:
    evidence: dict[str, list[dict[str, str]]] = {
        "console": [],
        "network": [],
    }
    page.on(
        "console",
        lambda message: evidence["console"].append({
            "type": message.type,
            "text": message.text,
        })
        if message.type == "error"
        else None,
    )
    page.on(
        "pageerror",
        lambda error: evidence["console"].append({
            "type": "pageerror",
            "text": str(error),
        }),
    )
    page.on(
        "requestfailed",
        lambda request: evidence["network"].append({
            "url": request.url,
            "error": str(request.failure),
        })
        if "unpkg.com" not in request.url
        else None,
    )
    return evidence


def _wait_for_fixture_terminal(page) -> None:
    page.wait_for_function(
        """() => (
            window.__mainlineAuditCaptures.length === 1
            && window.__mainlineAuditCaptureErrors.length === 0
            && typeof activeChatRequests !== 'undefined'
            && activeChatRequests.size === 0
            && document.querySelectorAll(
                '.message-wrapper.ai[data-guide-request-id] '
                + '.guide-presentation-root'
            ).length === 1
        )""",
        timeout=30_000,
    )


def _write_fixture_turn_bundle(
    *,
    page,
    turn_dir: Path,
    turn_id: str,
    viewport: str,
    evidence: dict[str, list[dict[str, str]]],
) -> None:
    capture = page.evaluate(
        "() => window.__mainlineAuditCaptures[0]"
    )
    if not isinstance(capture, dict):
        raise AuditBundleError("browser capture is unavailable")
    raw_bytes = capture.get("bytes")
    if (
        not isinstance(raw_bytes, list)
        or any(
            not isinstance(value, int)
            or value < 0
            or value > 255
            for value in raw_bytes
        )
    ):
        raise AuditBundleError("browser capture bytes are invalid")
    events = capture.get("events")
    if not isinstance(events, list):
        raise AuditBundleError("browser capture events are invalid")
    contracts = [
        event.get("data")
        for event in events
        if (
            isinstance(event, dict)
            and event.get("event") == "presentation_contract"
            and isinstance(event.get("data"), dict)
        )
    ]
    if len(contracts) != 1:
        raise AuditBundleError(
            "browser capture must contain one presentation contract"
        )
    request_id = page.evaluate(
        """() => document.querySelector(
            '.message-wrapper.ai[data-guide-request-id]'
        )?.dataset.guideRequestId || null"""
    )
    if not isinstance(request_id, str) or not request_id:
        raise AuditBundleError("browser request ID is unavailable")
    request_body = capture.get("body")
    try:
        parsed_body = (
            json.loads(request_body)
            if isinstance(request_body, str)
            else None
        )
    except json.JSONDecodeError as error:
        raise AuditBundleError("browser request JSON is invalid") from error
    _write_json(
        turn_dir / "request.json",
        {
            "turn_id": turn_id,
            "request_id": request_id,
            "viewport": VIEWPORTS[viewport],
            "method": capture.get("method"),
            "url": capture.get("url"),
            "body": parsed_body,
        },
    )
    (turn_dir / "stream.sse").write_bytes(bytes(raw_bytes))
    _write_json(
        turn_dir / "presentation-contract.json",
        contracts[0],
    )
    _write_json(
        turn_dir / "terminal-dom.json",
        _terminal_dom(
            page,
            request_id=request_id,
            terminal_kind="presentation",
        ),
    )
    _write_json(turn_dir / "console.json", evidence["console"])
    _write_json(turn_dir / "network.json", evidence["network"])
    page.screenshot(
        path=str(turn_dir / "screenshot.png"),
        full_page=True,
    )


def _terminal_dom(
    page,
    *,
    request_id: str,
    terminal_kind: str,
) -> dict[str, Any]:
    dom = page.evaluate(
        """input => {
            const { requestId, terminalKind } = input;
            const wrapper = document.querySelector(
                `.message-wrapper.ai[data-guide-request-id="${requestId}"]`
            );
            if (!wrapper) return null;
            const roots = Array.from(
                wrapper.querySelectorAll('.guide-presentation-root')
            );
            const root = roots[0] || null;
            const productIds = selector => (
                root
                    ? Array.from(root.querySelectorAll(selector))
                        .map(node => Number(node.dataset.guideProductId))
                        .filter(Number.isInteger)
                    : []
            );
            const inlineProductIds = productIds(
                '[data-guide-card-form="inline"]'
            );
            const shelfProductIds = productIds(
                '[data-guide-card-form="shelf"]'
            );
            const clarification = terminalKind === 'clarification';
            const legacyBubbles = clarification
                ? []
                : Array.from(
                    wrapper.querySelectorAll('.message-bubble')
                ).filter(bubble => !bubble.querySelector(
                    ':scope > .guide-presentation-root'
                ));
            return {
                request_id: requestId,
                terminal_kind: terminalKind,
                presentation_mode: root?.dataset.presentationMode || null,
                legacy_message_count: legacyBubbles.length,
                clarification_message_count: clarification
                    ? wrapper.querySelectorAll(
                        ':scope > .message-bubble'
                    ).length
                    : 0,
                legacy_product_card_count: root
                    ? root.querySelectorAll(
                        '.recommendation-card:not([data-guide-card-form])'
                    ).length
                    : 0,
                turn_presentation_root_count: roots.length,
                comparison_table_count: root
                    ? root.querySelectorAll(
                        '[data-guide-comparison-table="true"]'
                    ).length
                    : 0,
                visible_section_kinds: root
                    ? Array.from(
                        root.querySelectorAll('[data-section-kind]')
                    ).map(node => node.dataset.sectionKind)
                    : [],
                section_blocks: root
                    ? Array.from(
                        root.querySelectorAll('[data-section-kind]')
                    ).map(node => ({
                        kind: node.dataset.sectionKind,
                        text: node.innerText || ''
                    }))
                    : [],
                inline_product_ids: inlineProductIds,
                visible_product_ids: Array.from(
                    new Set([...inlineProductIds, ...shelfProductIds])
                ),
                shelf_product_ids: shelfProductIds,
                presentation_text: clarification
                    ? wrapper.innerText
                    : root?.innerText || '',
            };
        }""",
        {
            "requestId": request_id,
            "terminalKind": terminal_kind,
        },
    )
    if not isinstance(dom, dict):
        raise AuditBundleError("terminal DOM is unavailable")
    return dom


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def validate_audit_bundle(
    turn_dir: Path,
    *,
    expected_turn_id: str,
) -> None:
    if not turn_dir.is_dir():
        raise AuditBundleError("audit turn directory is missing")
    missing = REQUIRED_TURN_FILES - {
        path.name for path in turn_dir.iterdir()
    }
    if missing:
        raise AuditBundleError(
            "missing audit files: " + ", ".join(sorted(missing))
        )

    request = _read_object(turn_dir / "request.json")
    if request.get("turn_id") != expected_turn_id:
        raise AuditBundleError("request turn ID mismatch")
    request_id = request.get("request_id")
    if not isinstance(request_id, str) or not request_id:
        raise AuditBundleError("request ID is missing")

    contract = _read_object(
        turn_dir / "presentation-contract.json"
    )
    dom = _read_object(turn_dir / "terminal-dom.json")
    if dom.get("request_id") != request_id:
        raise AuditBundleError("DOM request ID mismatch")
    raw_stream = (turn_dir / "stream.sse").read_text(
        encoding="utf-8"
    )
    stream_events = _sse_events_from_sse(raw_stream)
    if contract.get("terminal_kind") == "clarification":
        _validate_clarification_bundle(
            terminal=contract,
            dom=dom,
            stream_events=stream_events,
        )
        if not (turn_dir / "screenshot.png").read_bytes():
            raise AuditBundleError("screenshot is empty")
        if _read_list(turn_dir / "console.json"):
            raise AuditBundleError("browser console is not empty")
        if _read_list(turn_dir / "network.json"):
            raise AuditBundleError(
                "browser network failures are not empty"
            )
        return
    if dom.get("presentation_mode") != contract.get("mode"):
        raise AuditBundleError("DOM contract mode mismatch")

    sections = tuple(
        contract["sections"]
        if isinstance(contract.get("sections"), list)
        else ()
    )
    expected_section_kinds = [
        section["kind"]
        for section in sections
        if (
            isinstance(section, dict)
            and isinstance(section.get("kind"), str)
        )
    ]
    if dom.get("visible_section_kinds") != expected_section_kinds:
        raise AuditBundleError("DOM section order mismatch")
    _validate_section_blocks(
        sections=sections,
        section_blocks=dom.get("section_blocks"),
    )
    expected_inline_product_ids = [
        section["product_id"]
        for section in sections
        if (
            isinstance(section, dict)
            and section.get("kind") == "product"
            and isinstance(section.get("product_id"), int)
        )
    ]
    if dom.get("inline_product_ids") != expected_inline_product_ids:
        raise AuditBundleError("DOM inline product IDs mismatch")
    visible_product_ids = contract.get("visible_product_ids")
    if not isinstance(visible_product_ids, list):
        raise AuditBundleError("contract visible product IDs are invalid")
    if dom.get("visible_product_ids") != visible_product_ids:
        raise AuditBundleError("DOM visible product IDs mismatch")
    if dom.get("shelf_product_ids") != visible_product_ids:
        raise AuditBundleError("DOM shelf product IDs mismatch")
    if dom.get("legacy_message_count") != 0:
        raise AuditBundleError("legacy message rendered")
    if dom.get("legacy_product_card_count") != 0:
        raise AuditBundleError("legacy product card rendered")
    if dom.get("turn_presentation_root_count") != 1:
        raise AuditBundleError("presentation root count mismatch")
    if (
        contract.get("mode") == "comparison"
        and dom.get("comparison_table_count") != 1
    ):
        raise AuditBundleError("comparison table count mismatch")

    presentation_text = dom.get("presentation_text")
    if not isinstance(presentation_text, str):
        raise AuditBundleError("DOM presentation text is invalid")
    normalized_presentation_text = _normalize_visible_text(
        presentation_text
    )
    missing_text = tuple(
        text
        for text in required_public_text(sections)
        if _normalize_visible_text(text)
        not in normalized_presentation_text
    )
    if missing_text:
        raise AuditBundleError("DOM presentation text mismatch")

    stream_contracts = tuple(
        data
        for event, data in stream_events
        if event == "presentation_contract"
    )
    if len(stream_contracts) != 1:
        raise AuditBundleError(
            "stream must contain one presentation contract"
        )
    if stream_contracts[0] != contract:
        raise AuditBundleError("stream presentation contract mismatch")
    if not (turn_dir / "screenshot.png").read_bytes():
        raise AuditBundleError("screenshot is empty")
    if _read_list(turn_dir / "console.json"):
        raise AuditBundleError("browser console is not empty")
    if _read_list(turn_dir / "network.json"):
        raise AuditBundleError("browser network failures are not empty")


def _validate_section_blocks(
    *,
    sections: tuple[object, ...],
    section_blocks: object,
) -> None:
    if not isinstance(section_blocks, list):
        raise AuditBundleError("DOM section blocks are missing")
    if len(section_blocks) != len(sections):
        raise AuditBundleError("DOM section block count mismatch")
    for section, block in zip(sections, section_blocks, strict=True):
        if not isinstance(section, dict) or not isinstance(block, dict):
            raise AuditBundleError("DOM section block is invalid")
        if block.get("kind") != section.get("kind"):
            raise AuditBundleError("DOM section block order mismatch")
        block_text = block.get("text")
        if not isinstance(block_text, str):
            raise AuditBundleError("DOM section block text is invalid")
        normalized_block = _normalize_visible_text(block_text)
        required = tuple(
            _normalize_visible_text(text)
            for text in _required_section_text(section)
        )
        cursor = 0
        for text in required:
            expected_count = sum(
                item.count(text) for item in required
            )
            if normalized_block.count(text) != expected_count:
                raise AuditBundleError("DOM section text mismatch")
            position = normalized_block.find(text, cursor)
            if position < 0:
                raise AuditBundleError("DOM section text mismatch")
            cursor = position + len(text)


def _required_section_text(
    section: dict[str, Any],
) -> tuple[str, ...]:
    direct_facts = section.get("direct_facts", ())
    return tuple(
        text
        for text in (
            section.get("copy_text"),
            *(
                item.get("display_value")
                for item in direct_facts
                if isinstance(item, dict)
            ),
            section.get("advisor_reason"),
        )
        if isinstance(text, str) and text
    )


def _validate_clarification_bundle(
    *,
    terminal: dict[str, Any],
    dom: dict[str, Any],
    stream_events: tuple[tuple[str, dict[str, Any]], ...],
) -> None:
    clarification = terminal.get("clarification")
    if not isinstance(clarification, dict):
        raise AuditBundleError("clarification terminal is invalid")
    question = clarification.get("question")
    code = clarification.get("clarification_code")
    if (
        not isinstance(question, str)
        or not question
        or not isinstance(code, str)
        or not code
    ):
        raise AuditBundleError("clarification terminal is invalid")
    if (
        dom.get("terminal_kind") != "clarification"
        or dom.get("presentation_mode") is not None
        or dom.get("legacy_message_count") != 0
        or dom.get("clarification_message_count") != 1
        or dom.get("legacy_product_card_count") != 0
        or dom.get("turn_presentation_root_count") != 0
        or dom.get("visible_section_kinds") != []
        or dom.get("inline_product_ids") != []
        or dom.get("visible_product_ids") != []
        or dom.get("shelf_product_ids") != []
    ):
        raise AuditBundleError("clarification DOM shape mismatch")
    presentation_text = dom.get("presentation_text")
    if (
        not isinstance(presentation_text, str)
        or question not in presentation_text
    ):
        raise AuditBundleError("clarification DOM text mismatch")
    event_names = tuple(event for event, _ in stream_events)
    clarification_events = tuple(
        data
        for event, data in stream_events
        if event == "clarify"
    )
    intent_events = tuple(
        data
        for event, data in stream_events
        if event == "intent"
    )
    if (
        event_names.count("presentation_contract") != 0
        or event_names.count("clarify") != 1
        or event_names.count("end") != 1
        or "error" in event_names
        or "message" in event_names
        or len(intent_events) != 1
        or intent_events[0].get("intent") != "clarify"
        or clarification_events[0] != clarification
    ):
        raise AuditBundleError("clarification stream mismatch")


def _sse_events_from_sse(
    raw: str,
) -> tuple[tuple[str, dict[str, Any]], ...]:
    events: list[tuple[str, dict[str, Any]]] = []
    for block in raw.replace("\r\n", "\n").split("\n\n"):
        event_name = None
        data_lines: list[str] = []
        for line in block.splitlines():
            if line.startswith("event:"):
                event_name = line.removeprefix("event:").strip()
            elif line.startswith("data:"):
                data_lines.append(line.removeprefix("data:").lstrip())
        if event_name is None or not data_lines:
            continue
        try:
            payload = json.loads("\n".join(data_lines))
        except json.JSONDecodeError as exc:
            raise AuditBundleError(
                "stream event is invalid JSON"
            ) from exc
        if not isinstance(payload, dict):
            raise AuditBundleError(
                "stream event must be an object"
            )
        events.append((event_name, payload))
    return tuple(events)


def _read_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AuditBundleError(f"invalid audit file: {path.name}") from exc
    if not isinstance(payload, dict):
        raise AuditBundleError(f"audit file must be object: {path.name}")
    return payload


def _read_list(path: Path) -> list[Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AuditBundleError(f"invalid audit file: {path.name}") from exc
    if not isinstance(payload, list):
        raise AuditBundleError(f"audit file must be list: {path.name}")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument(
        "--trajectory-set",
        choices=("fixture", "bounded", "release"),
        required=True,
    )
    parser.add_argument(
        "--viewport",
        choices=("desktop", "mobile", "all"),
        required=True,
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--attempt-context", type=Path)
    args = parser.parse_args()
    output = resolve_cli_output(
        trajectory_set=args.trajectory_set,
        output=args.output,
        attempt_context=args.attempt_context,
    )
    if args.trajectory_set == "fixture":
        report = run_fixture_browser_audits(
            base_url=args.base_url,
            output=output,
            viewport=args.viewport,
        )
    elif args.trajectory_set == "bounded":
        report = run_authorized_bounded_browser_audit(
            base_url=args.base_url,
            attempt_context=output,
            viewport=args.viewport,
        )
    else:
        raise SystemExit(
            "release audit requires its Task 12 runner"
        )
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "AuditBundleError",
    "BOUNDED_TRAJECTORIES",
    "FIXTURE_TURN_IDS",
    "REQUIRED_TURN_FILES",
    "fixture_sse_bytes",
    "required_public_text",
    "resolve_cli_output",
    "run_authorized_bounded_browser_audit",
    "run_bounded_browser_audit",
    "run_fixture_browser_audit",
    "run_fixture_browser_audits",
    "validate_bounded_contract",
    "validate_audit_bundle",
]
