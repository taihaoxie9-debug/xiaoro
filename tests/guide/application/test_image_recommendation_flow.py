from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import importlib
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from app.guide.adapters.catalog import CanonicalProductReader
from app.guide.adapters.catalog.canonical_guide_catalog import (
    CanonicalGuideCatalog,
)
from app.guide.adapters.catalog.seed_product_assets import (
    load_seed_product_assets,
)
from app.guide.adapters.image.safe_image_input import UntrustedImageInput
from app.guide.adapters.state import InMemoryConversationState
from app.guide.adapters.state.in_memory_image_bundle_state import (
    InMemoryImageBundleState,
)
from app.guide.adapters.state.in_memory_session_locks import (
    InMemorySessionLocks,
)
from app.guide.application.contracts import UserTurn
from app.guide.application.image_bundle_service import ImageBundleService
from app.guide.feedback.profile_contracts import ProfileOwnerRef
from app.guide.presentation.sse_events import (
    EndData,
    EndEvent,
    IntentData,
    IntentEvent,
    MessageData,
    MessageEvent,
)
from app.guide.retrieval.ports import CategoryRecord
from app.guide_runtime.composition import (
    compose_text_recommendation_orchestrator as _compose_text_recommendation_orchestrator,
)
from app.guide.understanding.image_contracts import (
    IdentityEvidenceConsistency,
    IdentityState,
    ImageIdentityObservation,
    ObservationState,
    OcrObservationState,
    VisualObservationState,
)
from app.guide.understanding.contracts import (
    UnderstandingGoal,
    UnderstandingIssue,
)
from app.guide.understanding.text_understanding import understand_text
from app.guide.understanding.turn_meaning_contracts import TurnMeaning
from tests.guide.semantic_test_port import exact_echo_understanding


def compose_text_recommendation_orchestrator(*args, **kwargs):
    kwargs.setdefault("understanding", exact_echo_understanding())
    return _compose_text_recommendation_orchestrator(*args, **kwargs)


ROOT = Path(__file__).resolve().parents[3]
INTERNAL_PUBLIC_TERMS = (
    "候选",
    "代码核对",
    "硬条件",
    "证据等级",
    "放行",
    "页面记录版本",
    "本轮筛选",
)


def _flow_type():
    try:
        module = importlib.import_module(
            "app.guide.application.image_recommendation_flow"
        )
    except ModuleNotFoundError:
        pytest.fail("image recommendation flow module is missing")
    return getattr(module, "ImageRecommendationOrchestrator")


def _jpeg(color: tuple[int, int, int]) -> bytes:
    image = Image.new("RGB", (4, 3), color=color)
    output = BytesIO()
    image.save(output, format="JPEG")
    image.close()
    return output.getvalue()


def _catalog() -> CanonicalGuideCatalog:
    canonical = ROOT / "data" / "canonical"
    reader = CanonicalProductReader.from_files(
        manifest_path=canonical / "core_products_v1_manifest.json",
        products_path=canonical / "core_products_v1.jsonl",
    )
    assets = load_seed_product_assets(
        manifest_path=canonical / "seed_product_images_v1_manifest.json",
        products_path=canonical / "seed_product_images_v1.jsonl",
        asset_root=ROOT,
    )
    return CanonicalGuideCatalog(reader, product_assets=assets)


def _approved_review_reader():
    from app.guide.retrieval.approved_review_assets import (
        load_approved_review_assets,
    )
    from app.guide.retrieval.review_reader import ReviewEvidenceReader

    source_root = ROOT / "data" / "guide_review_sources"
    loaded = load_approved_review_assets(
        manifest_path=(
            source_root
            / "approved_tmall_feed_reviews_v1_manifest.json"
        ),
        sources_path=(
            source_root / "approved_tmall_feed_reviews_v1.jsonl"
        ),
        expected_manifest_sha256=(
            "823c249166e93b4ab709b3423fa8a97a23e3ab3e7677e5d39d74abc21c165113"
        ),
    )
    return ReviewEvidenceReader(
        catalog=loaded.catalog,
        evidence=loaded.evidence,
    )


def _bundle(
    *,
    image_count: int = 1,
) -> tuple[ImageBundleService, object, list[bytes]]:
    service = ImageBundleService(
        state=InMemoryImageBundleState(max_bundles=8)
    )
    contents = [
        _jpeg((23 + index, 67, 101))
        for index in range(image_count)
    ]
    receipt = service.create(
        session_id="session-image",
        images=[
            UntrustedImageInput(
                file_name=f"product-{index}.jpg",
                declared_media_type="image/jpeg",
                content=content,
            )
            for index, content in enumerate(contents, start=1)
        ],
    )
    return service, receipt, contents


class FakeIdentityObserver:
    def __init__(
        self,
        *,
        identity_state: IdentityState = IdentityState.CONFIRMED,
        candidate_ids: tuple[int, ...] = (53, 55, 57),
    ) -> None:
        self.identity_state = identity_state
        self.candidate_ids = candidate_ids
        self.requests = []

    def observe(self, request):
        self.requests.append(request)
        if self.identity_state is IdentityState.VISUAL_UNAVAILABLE:
            return ImageIdentityObservation(
                image_id=request.image_id,
                observation_state=ObservationState.UNAVAILABLE,
                visual_state=VisualObservationState.UNAVAILABLE,
                ocr_state=OcrObservationState.NOT_RUN,
                identity_state=self.identity_state,
                confirmed_product_id=None,
                candidate_product_ids=(),
                visual_confidence=None,
                similarity_margin=None,
                model_name=None,
                weights_sha256=None,
                preprocessing_version=None,
                vector_dimension=None,
                index_sha256=None,
                ocr_brand_consistency=(
                    IdentityEvidenceConsistency.NOT_CHECKED
                ),
                ocr_product_name_consistency=(
                    IdentityEvidenceConsistency.NOT_CHECKED
                ),
            )
        confirmed = (
            self.candidate_ids[0]
            if self.identity_state is IdentityState.CONFIRMED
            else None
        )
        ocr_state = (
            OcrObservationState.OBSERVED
            if self.identity_state is IdentityState.OCR_CONFLICT
            else (
                OcrObservationState.NOT_CONFIGURED
                if self.identity_state is IdentityState.CONFIRMED
                else OcrObservationState.NOT_RUN
            )
        )
        return ImageIdentityObservation(
            image_id=request.image_id,
            observation_state=(
                ObservationState.COMPLETE
                if self.identity_state is IdentityState.OCR_CONFLICT
                else ObservationState.PARTIAL
            ),
            visual_state=VisualObservationState.OBSERVED,
            ocr_state=ocr_state,
            identity_state=self.identity_state,
            confirmed_product_id=confirmed,
            candidate_product_ids=self.candidate_ids,
            visual_confidence=0.99,
            similarity_margin=(
                0.2
                if self.identity_state is IdentityState.CONFIRMED
                else 0.01
            ),
            model_name="approved-openclip",
            weights_sha256="a" * 64,
            preprocessing_version="openclip-preprocess-v1",
            vector_dimension=512,
            index_sha256="b" * 64,
            ocr_brand_consistency=(
                IdentityEvidenceConsistency.CONFLICT
                if self.identity_state is IdentityState.OCR_CONFLICT
                else IdentityEvidenceConsistency.NOT_CHECKED
            ),
            ocr_product_name_consistency=(
                IdentityEvidenceConsistency.CONSISTENT
                if self.identity_state is IdentityState.OCR_CONFLICT
                else IdentityEvidenceConsistency.NOT_CHECKED
            ),
        )


class SequencedIdentityObserver:
    def __init__(
        self,
        product_ids: tuple[int, ...],
        *,
        states: tuple[IdentityState, ...] | None = None,
    ) -> None:
        self.product_ids = product_ids
        self.states = states or (IdentityState.CONFIRMED,) * len(product_ids)
        self.requests = []

    def observe(self, request):
        index = len(self.requests)
        self.requests.append(request)
        product_id = self.product_ids[index]
        state = self.states[index]
        candidates = (
            product_id,
            next(
                candidate
                for candidate in (53, 55, 57)
                if candidate != product_id
            ),
        )
        observer = FakeIdentityObserver(
            identity_state=state,
            candidate_ids=candidates,
        )
        return observer.observe(request)


class RecordingStandardProcessor:
    def __init__(self) -> None:
        self.calls = []

    def stream_understanding_body(
        self,
        turn,
        *,
        understanding,
        route_decision,
        product_bindings,
    ):
        self.calls.append(
            (
                turn,
                understanding,
                route_decision,
                product_bindings,
            )
        )
        yield IntentEvent(data=IntentData(mode="knowledge"))
        yield MessageEvent(data=MessageData(content="标准商品知识回答"))
        yield EndEvent(
            data=EndData(
                conversation_version=turn.conversation_version
            )
        )


def test_semantic_image_count_reads_authorized_bundle() -> None:
    service, receipt, _ = _bundle(image_count=3)
    catalog = _catalog()
    flow = _flow_type()(
        image_bundles=service,
        identity_observer=FakeIdentityObserver(),
        category_catalog=catalog,
        decision_facts=catalog,
        presentation_facts=catalog,
    )
    turn = _turn(receipt, "比较这三张图")

    assert flow.semantic_image_count(turn) == 3


def _turn(receipt, message: str) -> UserTurn:
    return UserTurn(
        session_id="session-image",
        message=message,
        image_bundle_id=receipt.bundle_id,
        image_bundle_version=receipt.version,
        image_bundle_token=receipt.owner_token,
        conversation_version=0,
    )


def _image_meaning(
    operation: str,
    *,
    observations: tuple[dict[str, object], ...] = (),
    references: tuple[dict[str, object], ...] = (),
    topic: str | None = "sunscreen",
) -> TurnMeaning:
    return TurnMeaning.model_validate(
        {
            "operation_hint": operation,
            "topic_hint": topic,
            "continuity_hint": "new_task",
            "subject_scope_hint": "self",
            "reference_mentions": references,
            "product_mentions": [],
            "budget_candidates": [],
            "observation_candidates": observations,
            "preference_candidates": [],
            "relative_candidates": [],
            "consultation_hypothesis": None,
            "next_observation_gap": None,
            "question_meaning": "图片商品问题",
            "safety_language": "ordinary",
        },
        strict=True,
    )


def test_single_image_product_batch_quantity_reuses_recommendation() -> None:
    service, receipt, _ = _bundle()
    catalog = _catalog()
    flow = _flow_type()(
        image_bundles=service,
        identity_observer=FakeIdentityObserver(
            candidate_ids=(53, 54, 101, 130),
        ),
        category_catalog=catalog,
        decision_facts=catalog,
        presentation_facts=catalog,
        max_results=10,
    )
    turn = _turn(
        receipt,
        "帮我找两款相似的，并说明哪里相似、哪里不同",
    )
    understanding = understand_text(turn.message).model_copy(
        update={
            "goal": UnderstandingGoal.COMPARISON,
            "topic": None,
            "references": [],
            "uncertainties": [],
        },
        deep=True,
    )
    meaning = _image_meaning(
        "comparison",
        references=(
            {
                "raw_text": "两款",
                "object_family_hint": "product",
                "ordinal_hint": None,
                "plurality_hint": "batch",
            },
        ),
    )

    events = list(
        flow.stream_understanding(
            turn,
            meaning=meaning,
            understanding=understanding,
            snapshot=None,
        )
    )

    assert next(
        event for event in events if event.event == "intent"
    ).data.mode == "image_recommend"
    cards = next(
        event.data.cards for event in events if event.event == "products"
    )
    assert cards
    assert 53 not in {card.product_id for card in cards}


def test_single_image_similarity_goal_reuses_recommendation() -> None:
    service, receipt, _ = _bundle()
    catalog = _catalog()
    flow = _flow_type()(
        image_bundles=service,
        identity_observer=FakeIdentityObserver(
            candidate_ids=(53, 54, 101, 130),
        ),
        category_catalog=catalog,
        decision_facts=catalog,
        presentation_facts=catalog,
        max_results=10,
    )
    turn = _turn(
        receipt,
        "帮我找两款相似的，并说明哪里相似、哪里不同",
    )
    understanding = understand_text(turn.message).model_copy(
        update={
            "goal": UnderstandingGoal.IMAGE_SIMILARITY,
            "topic": None,
            "references": [],
            "uncertainties": [],
        },
        deep=True,
    )

    events = list(
        flow.stream_understanding(
            turn,
            meaning=_image_meaning("image_similarity"),
            understanding=understanding,
            snapshot=None,
        )
    )

    assert next(
        event for event in events if event.event == "intent"
    ).data.mode == "image_recommend"
    cards = next(
        event.data.cards for event in events if event.event == "products"
    )
    assert len(cards) == 2
    assert 53 not in {card.product_id for card in cards}


def test_single_image_anchor_topic_clears_missing_category_issue() -> None:
    service, receipt, _ = _bundle()
    catalog = _catalog()
    flow = _flow_type()(
        image_bundles=service,
        identity_observer=FakeIdentityObserver(
            candidate_ids=(53, 55, 57),
        ),
        category_catalog=catalog,
        decision_facts=catalog,
        presentation_facts=catalog,
        max_results=10,
    )
    turn = _turn(
        receipt,
        "找两款相似的，预算150以内，更清爽一点",
    )
    understanding = understand_text(turn.message).model_copy(
        update={
            "goal": UnderstandingGoal.RECOMMENDATION,
            "topic": None,
            "uncertainties": [
                UnderstandingIssue(
                    code="missing_category",
                    detail="请明确要找的商品品类。",
                )
            ],
        },
        deep=True,
    )

    events = list(
        flow.stream_understanding(
            turn,
            meaning=_image_meaning(
                "recommendation",
                topic=None,
            ),
            understanding=understanding,
            snapshot=None,
        )
    )

    assert next(
        event for event in events if event.event == "intent"
    ).data.mode == "image_recommend"
    assert any(event.event == "products" for event in events)


def test_unified_image_entry_accepts_pretranslated_semantics() -> None:
    service, receipt, _ = _bundle()
    observer = FakeIdentityObserver()
    catalog = _catalog()
    flow = _flow_type()(
        image_bundles=service,
        identity_observer=observer,
        category_catalog=catalog,
        decision_facts=catalog,
        presentation_facts=catalog,
        max_results=10,
    )
    turn = _turn(receipt, "这是什么商品")

    events = list(
        flow.stream_understanding(
            turn,
            meaning=_image_meaning("knowledge"),
            understanding=understand_text(turn.message),
            snapshot=None,
        )
    )

    assert [event.event for event in events][0] == "start"
    assert next(
        event for event in events if event.event == "intent"
    ).data.mode == "image_identity"
    presentation = next(
        event
        for event in events
        if event.event == "presentation_contract"
    )
    assert presentation.data.mode == "image_identity"
    assert observer.requests


def test_unified_image_product_question_delegates_standard_processor() -> None:
    service, receipt, _ = _bundle()
    observer = FakeIdentityObserver()
    catalog = _catalog()
    standard = RecordingStandardProcessor()
    flow = _flow_type()(
        image_bundles=service,
        identity_observer=observer,
        category_catalog=catalog,
        decision_facts=catalog,
        presentation_facts=catalog,
        standard_processor=standard,
        max_results=10,
    )
    turn = _turn(receipt, "这款质地和用法怎么样")
    understanding = understand_text(turn.message).model_copy(
        update={
            "goal": UnderstandingGoal.KNOWLEDGE,
            "uncertainties": [],
            "question_meaning": "质地和用法",
        },
        deep=True,
    )

    events = list(
        flow.stream_understanding(
            turn,
            meaning=_image_meaning("knowledge"),
            understanding=understanding,
            snapshot=None,
        )
    )

    assert len(standard.calls) == 1
    route = standard.calls[0][2]
    bindings = standard.calls[0][3]
    assert route.processor == "product_knowledge"
    assert [item.product_id for item in bindings] == [53]
    assert any(
        event.event == "image_observation" for event in events
    )
    assert next(
        event for event in events if event.event == "message"
    ).data.content == "标准商品知识回答"


def test_unified_image_similarity_delegates_standard_recommendation() -> None:
    service, receipt, _ = _bundle()
    observer = FakeIdentityObserver(candidate_ids=(53, 55, 57))
    catalog = _catalog()
    standard = RecordingStandardProcessor()
    flow = _flow_type()(
        image_bundles=service,
        identity_observer=observer,
        category_catalog=catalog,
        decision_facts=catalog,
        presentation_facts=catalog,
        standard_processor=standard,
        max_results=10,
    )
    turn = _turn(receipt, "照这张图找两款相似的")
    understanding = understand_text(turn.message).model_copy(
        update={
            "goal": UnderstandingGoal.IMAGE_SIMILARITY,
            "uncertainties": [],
        },
        deep=True,
    )

    events = list(
        flow.stream_understanding(
            turn,
            meaning=_image_meaning("image_similarity"),
            understanding=understanding,
            snapshot=None,
        )
    )

    assert len(standard.calls) == 1
    route = standard.calls[0][2]
    bindings = standard.calls[0][3]
    assert route.processor == "recommendation"
    assert [item.product_id for item in bindings] == [53]
    assert next(
        event for event in events if event.event == "message"
    ).data.content == "标准商品知识回答"


def test_unified_image_suitability_delegates_standard_processor() -> None:
    service, receipt, _ = _bundle()
    observer = FakeIdentityObserver(candidate_ids=(53, 55, 57))
    catalog = _catalog()
    standard = RecordingStandardProcessor()
    flow = _flow_type()(
        image_bundles=service,
        identity_observer=observer,
        category_catalog=catalog,
        decision_facts=catalog,
        presentation_facts=catalog,
        standard_processor=standard,
        max_results=10,
    )
    turn = _turn(receipt, "这款适合敏感肌吗")
    understanding = understand_text(turn.message).model_copy(
        update={
            "goal": UnderstandingGoal.SUITABILITY,
            "uncertainties": [],
        },
        deep=True,
    )

    events = list(
        flow.stream_understanding(
            turn,
            meaning=_image_meaning("suitability"),
            understanding=understanding,
            snapshot=None,
        )
    )

    assert len(standard.calls) == 1
    route = standard.calls[0][2]
    bindings = standard.calls[0][3]
    assert route.processor == "product_knowledge"
    assert [item.product_id for item in bindings] == [53]
    assert next(
        event for event in events if event.event == "message"
    ).data.content == "标准商品知识回答"


def test_unified_multi_image_safety_precedes_comparison() -> None:
    service, receipt, _ = _bundle(image_count=2)
    catalog = _catalog()
    flow = _flow_type()(
        image_bundles=service,
        identity_observer=SequencedIdentityObserver((53, 55)),
        category_catalog=catalog,
        decision_facts=catalog,
        presentation_facts=catalog,
        max_results=10,
    )
    turn = _turn(receipt, "比较这两张图，我现在破皮了")
    meaning = _image_meaning(
        "comparison",
        observations=(
            {
                "observation_id": "obs_broken",
                "code": "broken_skin",
                "present": True,
                "qualifier": None,
                "raw_text": "破皮",
                "location": None,
                "trigger": None,
                "duration": "current",
                "severity": "moderate",
            },
        ),
    )

    events = list(
        flow.stream_understanding(
            turn,
            meaning=meaning,
            understanding=understand_text(turn.message),
            snapshot=None,
        )
    )

    assert not any(event.event == "products" for event in events)
    assert next(
        event for event in events if event.event == "intent"
    ).data.mode == "clarify"
    clarify = next(
        event for event in events if event.event == "clarify"
    )
    assert "暂停" in clarify.data.question


def test_unified_multi_image_delegates_standard_comparison() -> None:
    service, receipt, _ = _bundle(image_count=2)
    catalog = _catalog()
    standard = RecordingStandardProcessor()
    flow = _flow_type()(
        image_bundles=service,
        identity_observer=SequencedIdentityObserver((53, 55)),
        category_catalog=catalog,
        decision_facts=catalog,
        presentation_facts=catalog,
        standard_processor=standard,
        max_results=10,
    )
    turn = _turn(receipt, "比较这两张图")
    understanding = understand_text(turn.message).model_copy(
        update={
            "goal": UnderstandingGoal.COMPARISON,
            "uncertainties": [],
        },
        deep=True,
    )

    events = list(
        flow.stream_understanding(
            turn,
            meaning=_image_meaning("comparison"),
            understanding=understanding,
            snapshot=None,
        )
    )

    assert len(standard.calls) == 1
    route = standard.calls[0][2]
    bindings = standard.calls[0][3]
    assert route.processor == "comparison"
    assert [item.product_id for item in bindings] == [53, 55]
    assert next(
        event for event in events if event.event == "message"
    ).data.content == "标准商品知识回答"


def test_image_flow_uses_similarity_only_for_recall_then_hard_budget() -> None:
    service, receipt, contents = _bundle()
    observer = FakeIdentityObserver()
    catalog = _catalog()
    flow = _flow_type()(
        image_bundles=service,
        identity_observer=observer,
        category_catalog=catalog,
        decision_facts=catalog,
        presentation_facts=catalog,
        max_results=10,
    )

    events = list(flow.stream(_turn(receipt, "100元以内找相似款")))

    observation = next(
        event
        for event in events
        if event.event == "image_observation"
    )
    products = next(
        event for event in events if event.event == "products"
    )
    decision = next(
        event
        for event in events
        if event.event == "decision_process"
    )
    card_display = next(
        event
        for event in events
        if event.event == "card_display_contract"
    )
    assert observation.data.observation.confirmed_product_id == 53
    assert observation.data.observation.model_name == "approved-openclip"
    assert observation.data.observation.index_sha256 == "b" * 64
    assert [card.product_id for card in products.data.cards] == [57, 55]
    assert decision.data.winner_status == "SELECTED"
    assert decision.data.ordered_product_ids == [57, 55]
    assert card_display.data.model_dump(mode="json") == {
        "mode": "recommendation",
        "visible_product_ids": [57, 55],
        "max_cards": 2,
        "reason": "recommendation",
    }
    names = [event.event for event in events]
    assert names.index("answer_contract") < names.index(
        "card_display_contract"
    )
    assert names.index("card_display_contract") < names.index("products")
    assert all(card.image_url for card in products.data.cards)
    assert all(card.detail_url for card in products.data.cards)
    assert observer.requests[0].content == contents[0]
    assert observer.requests[0].max_results == 10


def test_similarity_excludes_source_and_explains_shared_difference() -> None:
    service, receipt, _ = _bundle()
    catalog = _catalog()
    flow = _flow_type()(
        image_bundles=service,
        identity_observer=FakeIdentityObserver(
            candidate_ids=(53, 55, 57),
        ),
        category_catalog=catalog,
        decision_facts=catalog,
        presentation_facts=catalog,
        max_results=10,
    )

    events = list(flow.stream(_turn(receipt, "500元以内找相似款")))

    products = next(
        event for event in events if event.event == "products"
    )
    message = next(
        event for event in events if event.event == "message"
    ).data.content
    assert 53 not in {
        card.product_id for card in products.data.cards
    }
    assert "相似点" in message
    assert "不同点" in message


def test_image_flow_public_events_hide_internal_language() -> None:
    service, receipt, _ = _bundle()
    catalog = _catalog()
    flow = _flow_type()(
        image_bundles=service,
        identity_observer=FakeIdentityObserver(),
        category_catalog=catalog,
        decision_facts=catalog,
        presentation_facts=catalog,
        max_results=10,
    )

    events = list(flow.stream(_turn(receipt, "100元以内找相似款")))
    payload = "\n".join(event.model_dump_json() for event in events)

    for term in INTERNAL_PUBLIC_TERMS:
        assert term not in payload


def test_image_retrieval_preserves_canonical_category_state() -> None:
    service, receipt, _ = _bundle()
    payload = service.authorize_payloads(
        bundle_id=receipt.bundle_id,
        version=receipt.version,
        session_id="session-image",
        owner_token=receipt.owner_token,
    )[0]
    observation = FakeIdentityObserver(
        candidate_ids=(53, 55),
    ).observe(
        SimpleNamespace(
            image_id=payload.image_id,
            content=b"",
            max_results=10,
        )
    )
    module = importlib.import_module(
        "app.guide.application.image_recommendation_flow"
    )

    retrieval = module._image_retrieval_result(
        observation,
        category_records={
            53: CategoryRecord(
                product_id=53,
                value="防晒乳",
                state="known",
            ),
            55: CategoryRecord(
                product_id=55,
                value=None,
                state="conflict",
            ),
        },
    )

    assert [
        candidate.canonical_category_state
        for candidate in retrieval.candidates
    ] == ["known", "conflict"]


def test_unconfirmed_image_identity_never_enters_decision_or_cards() -> None:
    service, receipt, _ = _bundle()
    observer = FakeIdentityObserver(
        identity_state=IdentityState.AMBIGUOUS_CANDIDATES,
        candidate_ids=(53, 55),
    )
    catalog = _catalog()
    flow = _flow_type()(
        image_bundles=service,
        identity_observer=observer,
        category_catalog=catalog,
        decision_facts=catalog,
        presentation_facts=catalog,
        max_results=10,
    )

    events = list(flow.stream(_turn(receipt, "找相似款")))

    assert any(event.event == "image_observation" for event in events)
    assert not any(event.event == "decision_process" for event in events)
    assert not any(event.event == "products" for event in events)
    error = next(event for event in events if event.event == "error")
    assert error.data.code == "IMAGE_IDENTITY_UNCONFIRMED"


def test_confirmed_image_and_text_category_conflict_clarifies() -> None:
    service, receipt, _ = _bundle()
    catalog = _catalog()
    flow = _flow_type()(
        image_bundles=service,
        identity_observer=FakeIdentityObserver(
            candidate_ids=(53, 38, 91),
        ),
        category_catalog=catalog,
        decision_facts=catalog,
        presentation_facts=catalog,
        max_results=10,
    )

    events = list(flow.stream(_turn(receipt, "500元内修护精华")))

    clarify = next(
        event for event in events if event.event == "clarify"
    )
    assert "图片商品品类与文字指定品类不一致" in clarify.data.question
    assert not any(
        event.event == "decision_process" for event in events
    )
    assert not any(event.event == "products" for event in events)
    assert events[-1].event == "end"


def test_single_image_suitability_emits_typed_result_and_exact_one_card(
) -> None:
    service, receipt, _ = _bundle()
    catalog = _catalog()
    flow = _flow_type()(
        image_bundles=service,
        identity_observer=FakeIdentityObserver(candidate_ids=(53, 55)),
        category_catalog=catalog,
        decision_facts=catalog,
        presentation_facts=catalog,
        max_results=10,
    )

    events = list(flow.stream(_turn(receipt, "这款适合敏感肌吗")))

    intent = next(event for event in events if event.event == "intent")
    decision = next(
        event for event in events if event.event == "decision_process"
    )
    products = next(event for event in events if event.event == "products")
    card_display = next(
        event
        for event in events
        if event.event == "card_display_contract"
    )
    assert intent.data.mode == "image_suitability"
    assert decision.data.ordered_product_ids == [53]
    assert decision.data.winner_status == "insufficient_evidence"
    assert decision.data.suitability_data is not None
    assert decision.data.suitability_data.status == "insufficient_evidence"
    assert decision.data.suitability_data.reference.ordinal == 1
    assert decision.data.suitability_data.reference.product_id == 53
    assert [card.product_id for card in products.data.cards] == [53]
    assert card_display.data.model_dump(mode="json") == {
        "mode": "single",
        "visible_product_ids": [53],
        "max_cards": 1,
        "reason": "product",
    }


def test_single_image_suitability_without_context_clarifies_with_zero_cards(
) -> None:
    service, receipt, _ = _bundle()
    catalog = _catalog()
    flow = _flow_type()(
        image_bundles=service,
        identity_observer=FakeIdentityObserver(candidate_ids=(53, 55)),
        category_catalog=catalog,
        decision_facts=catalog,
        presentation_facts=catalog,
        max_results=10,
    )

    events = list(flow.stream(_turn(receipt, "这款适合我吗")))

    assert next(
        event for event in events if event.event == "intent"
    ).data.mode == "clarify"
    assert any(event.event == "clarify" for event in events)
    assert not any(event.event == "answer_contract" for event in events)
    assert not any(event.event == "card_display_contract" for event in events)
    assert not any(event.event == "products" for event in events)
    assert events[-1].event == "end"


@pytest.mark.parametrize(
    ("profile_source", "expected_context_source"),
    [
        ("confirmed_session", "confirmed_session"),
        ("long_term_profile", "long_term_profile"),
    ],
)
def test_single_image_suitability_uses_server_resolved_profile_context(
    profile_source: str,
    expected_context_source: str,
) -> None:
    from app.guide.feedback.profile_contracts import (
        ConfirmedProfileFact,
        ProfileOwnerRef,
    )
    from app.guide.feedback.profile_policy import (
        ConfirmedSessionFact,
        resolve_profile_context,
    )
    from app.guide.feedback.profile_state import ProfileSnapshot

    service, receipt, _ = _bundle()
    catalog = _catalog()
    owner = ProfileOwnerRef(
        scope="anonymous_browser",
        subject_id="profile_image_suitability_0001",
    )
    if profile_source == "confirmed_session":
        resolved = resolve_profile_context(
            confirmed_session=[
                ConfirmedSessionFact(
                    field="skin_type",
                    value="dry",
                    source_turn_id="turn_confirmed_session_0001",
                    source_kind="confirmed_consultation",
                )
            ]
        )
    else:
        resolved = resolve_profile_context(
            profile=ProfileSnapshot(
                owner=owner,
                version=3,
                facts=[
                    ConfirmedProfileFact(
                        owner=owner,
                        field="skin_type",
                        value="dry",
                        source_turn_id="turn_long_term_profile_0001",
                        source_kind="confirmed_consultation",
                        confirmed_at=datetime(
                            2026,
                            8,
                            9,
                            tzinfo=UTC,
                        ),
                        profile_version=3,
                    )
                ],
            )
        )
    resolver_calls = []

    def resolve_profile(**kwargs):
        resolver_calls.append(kwargs)
        return resolved

    flow = _flow_type()(
        image_bundles=service,
        identity_observer=FakeIdentityObserver(candidate_ids=(53, 55)),
        category_catalog=catalog,
        decision_facts=catalog,
        presentation_facts=catalog,
        profile_owner_factory=lambda session_id: owner,
        profile_resolver=resolve_profile,
        max_results=10,
    )

    events = list(flow.stream(_turn(receipt, "这款适合我吗")))

    decision = next(
        event for event in events if event.event == "decision_process"
    )
    assert decision.data.suitability_data is not None
    assert (
        decision.data.suitability_data.context_source
        == expected_context_source
    )
    assert decision.data.suitability_data.skin_target == "dry"
    assert resolver_calls == [
        {
            "session_id": "session-image",
            "profile_owner": owner,
        }
    ]


def test_single_image_suitability_explicit_skin_precedes_profile() -> None:
    service, receipt, _ = _bundle()
    catalog = _catalog()
    resolver_calls = []

    def resolve_profile(**kwargs):
        resolver_calls.append(kwargs)
        raise AssertionError("explicit skin must not read stored profile")

    flow = _flow_type()(
        image_bundles=service,
        identity_observer=FakeIdentityObserver(candidate_ids=(53, 55)),
        category_catalog=catalog,
        decision_facts=catalog,
        presentation_facts=catalog,
        profile_owner_factory=lambda session_id: pytest.fail(
            "explicit skin must not resolve a profile owner"
        ),
        profile_resolver=resolve_profile,
        max_results=10,
    )

    events = list(flow.stream(_turn(receipt, "这款适合敏感肌吗")))

    decision = next(
        event for event in events if event.event == "decision_process"
    )
    assert decision.data.suitability_data is not None
    assert (
        decision.data.suitability_data.context_source
        == "current_explicit_input"
    )
    assert decision.data.suitability_data.skin_target == "sensitive"
    assert resolver_calls == []


def test_single_image_suitability_prefers_trusted_turn_owner() -> None:
    from app.guide.feedback.profile_contracts import ProfileOwnerRef
    from app.guide.feedback.profile_policy import (
        ConfirmedSessionFact,
        resolve_profile_context,
    )

    service, receipt, _ = _bundle()
    catalog = _catalog()
    legacy_owner = ProfileOwnerRef(
        scope="anonymous_browser",
        subject_id="profile_image_legacy_owner_0001",
    )
    actor_owner = ProfileOwnerRef(
        scope="local_demo",
        subject_id="feedback-browser-" + "a" * 64,
    )
    resolver_calls = []

    def resolve_profile(**kwargs):
        resolver_calls.append(kwargs)
        return resolve_profile_context(
            confirmed_session=[
                ConfirmedSessionFact(
                    field="skin_type",
                    value="dry",
                    source_turn_id="turn_trusted_actor_owner_0001",
                    source_kind="confirmed_consultation",
                )
            ]
        )

    flow = _flow_type()(
        image_bundles=service,
        identity_observer=FakeIdentityObserver(candidate_ids=(53, 55)),
        category_catalog=catalog,
        decision_facts=catalog,
        presentation_facts=catalog,
        profile_owner_factory=lambda session_id: legacy_owner,
        profile_resolver=resolve_profile,
        max_results=10,
    )
    turn = _turn(receipt, "这款适合我吗").model_copy(
        update={"profile_owner": actor_owner}
    )

    events = list(flow.stream(turn))

    assert any(event.event == "decision_process" for event in events)
    assert resolver_calls == [
        {
            "session_id": "session-image",
            "profile_owner": actor_owner,
        }
    ]


def test_image_scenario_emits_evidence_after_final_sorting() -> None:
    service, receipt, _ = _bundle()
    catalog = _catalog()
    flow = _flow_type()(
        image_bundles=service,
        identity_observer=FakeIdentityObserver(),
        category_catalog=catalog,
        scenario_evidence=catalog,
        decision_facts=catalog,
        presentation_facts=catalog,
        review_evidence=_approved_review_reader(),
        max_results=10,
    )

    events = list(
        flow.stream(
            _turn(receipt, "500元内长时间户外防晒，找相似款")
        )
    )

    names = [event.event for event in events]
    products = next(
        event.data.cards for event in events if event.event == "products"
    )
    scenario = next(
        event.data.records
        for event in events
        if event.event == "scenario_evidence"
    )
    reviews = next(
        event.data
        for event in events
        if event.event == "review_evidence"
    )
    assert [card.product_id for card in products] == [57, 55]
    assert sorted({record.product_id for record in scenario}) == [
        55,
        57,
    ]
    assert reviews.approved_source_count == 6
    assert [item.product_id for item in reviews.results] == [57, 55]
    assert [len(item.evidence) for item in reviews.results] == [0, 2]
    assert len(reviews.summaries) == 1
    assert reviews.summaries[0].product_id == 55
    assert len(reviews.summaries[0].source_facts) == 2
    assert names.index("scenario_evidence") < names.index(
        "review_evidence"
    )
    assert names.index("review_evidence") < names.index("pitfalls")
    assert names.index("pitfalls") < names.index("decision_process")


def test_image_suitability_emits_safe_ocr_and_canonical_citations_without_reorder(
) -> None:
    service, receipt, _ = _bundle()
    catalog = _catalog()
    flow = _flow_type()(
        image_bundles=service,
        identity_observer=FakeIdentityObserver(candidate_ids=(53, 55)),
        category_catalog=catalog,
        decision_facts=catalog,
        presentation_facts=catalog,
        max_results=10,
    )

    events = list(flow.stream(_turn(receipt, "这款适合敏感肌吗")))

    products = next(event for event in events if event.event == "products")
    citations = next(
        event for event in events if event.event == "citations"
    )
    payload = citations.model_dump_json()
    assert [card.product_id for card in products.data.cards] == [53]
    assert {
        citation.source_kind for citation in citations.data.citations
    } == {
        "visual_model",
        "ocr_observation",
        "canonical",
    }
    assert "raw_ocr" not in payload
    assert "raw_text" not in payload
    assert "candidate_product_ids" not in payload


def test_two_image_flow_observes_in_order_and_emits_exact_comparison_cards(
) -> None:
    service, receipt, _ = _bundle(image_count=2)
    observer = SequencedIdentityObserver((53, 55))
    catalog = _catalog()
    flow = _flow_type()(
        image_bundles=service,
        identity_observer=observer,
        category_catalog=catalog,
        decision_facts=catalog,
        presentation_facts=catalog,
        max_results=10,
    )

    events = list(flow.stream(_turn(receipt, "找相似款")))

    observations = [
        event.data.observation
        for event in events
        if event.event == "image_observation"
    ]
    products = next(
        event for event in events if event.event == "products"
    )
    contract = next(
        event
        for event in events
        if event.event == "card_display_contract"
    )
    assert [item.confirmed_product_id for item in observations] == [53, 55]
    assert [request.image_id for request in observer.requests] == [
        item.image_id for item in observations
    ]
    assert [card.product_id for card in products.data.cards] == [53, 55]
    assert all(card.skin_match == "unknown" for card in products.data.cards)
    assert all(not card.matched_efficacies for card in products.data.cards)
    assert contract.data.model_dump(mode="json") == {
        "mode": "comparison",
        "visible_product_ids": [53, 55],
        "max_cards": 2,
        "reason": "comparison",
    }


@pytest.mark.parametrize(
    "product_ids",
    [
        (53, 55, 57),
    ],
)
def test_three_image_flow_preserves_ordinals_and_exact_cards(
    product_ids: tuple[int, ...],
) -> None:
    service, receipt, _ = _bundle(image_count=len(product_ids))
    observer = SequencedIdentityObserver(product_ids)
    catalog = _catalog()
    flow = _flow_type()(
        image_bundles=service,
        identity_observer=observer,
        category_catalog=catalog,
        decision_facts=catalog,
        presentation_facts=catalog,
        max_results=10,
    )

    events = list(flow.stream(_turn(receipt, "比较这些图片")))

    observations = [
        event.data.observation
        for event in events
        if event.event == "image_observation"
    ]
    decision = next(
        event for event in events if event.event == "decision_process"
    )
    products = next(event for event in events if event.event == "products")
    contract = next(
        event
        for event in events
        if event.event == "card_display_contract"
    )
    assert [item.confirmed_product_id for item in observations] == list(
        product_ids
    )
    assert [
        reference.ordinal
        for reference in decision.data.comparison_data.references
    ] == list(range(1, len(product_ids) + 1))
    assert [
        reference.product_id
        for reference in decision.data.comparison_data.references
    ] == list(product_ids)
    assert decision.data.comparison_data.status in {
        "winner",
        "tie",
        "insufficient_evidence",
    }
    assert [
        card.product_id for card in products.data.cards
    ] == list(product_ids)
    assert contract.data.model_dump(mode="json") == {
        "mode": "comparison",
        "visible_product_ids": list(product_ids),
        "max_cards": len(product_ids),
        "reason": "comparison",
    }


def test_four_image_comparison_asks_user_to_keep_three() -> None:
    service, receipt, _ = _bundle(image_count=4)
    observer = SequencedIdentityObserver((53, 55, 57, 58))
    catalog = _catalog()
    flow = _flow_type()(
        image_bundles=service,
        identity_observer=observer,
        category_catalog=catalog,
        decision_facts=catalog,
        presentation_facts=catalog,
        max_results=10,
    )

    events = list(flow.stream(_turn(receipt, "比较这些图片")))

    assert observer.requests == []
    clarify = next(
        event for event in events if event.event == "clarify"
    )
    assert "最多比较三款" in clarify.data.question
    assert not any(event.event == "products" for event in events)


def test_two_image_unconfirmed_identity_stops_after_both_observations() -> None:
    service, receipt, _ = _bundle(image_count=2)
    observer = SequencedIdentityObserver(
        (53, 55),
        states=(
            IdentityState.CONFIRMED,
            IdentityState.LOW_CONFIDENCE,
        ),
    )
    catalog = _catalog()
    flow = _flow_type()(
        image_bundles=service,
        identity_observer=observer,
        category_catalog=catalog,
        decision_facts=catalog,
        presentation_facts=catalog,
        max_results=10,
    )

    events = list(flow.stream(_turn(receipt, "比较这两张图")))

    assert len(observer.requests) == 2
    assert sum(
        event.event == "image_observation" for event in events
    ) == 2
    assert any(event.event == "clarify" for event in events)
    assert not any(event.event == "decision_process" for event in events)
    assert not any(event.event == "products" for event in events)


def test_forged_bundle_ownership_stops_before_observation() -> None:
    service, receipt, _ = _bundle(image_count=2)
    observer = SequencedIdentityObserver((53, 55))
    catalog = _catalog()
    flow = _flow_type()(
        image_bundles=service,
        identity_observer=observer,
        category_catalog=catalog,
        decision_facts=catalog,
        presentation_facts=catalog,
        max_results=10,
    )
    turn = _turn(receipt, "比较这两张图").model_copy(
        update={"image_bundle_token": "owner_wrong-token-with-entropy-12345"}
    )

    events = list(flow.stream(turn))

    assert observer.requests == []
    assert [event.event for event in events] == ["start", "error"]
    assert events[-1].data.code == "IMAGE_BUNDLE_UNAVAILABLE"


def test_confirmed_unsupported_category_returns_public_error() -> None:
    class UnsupportedCategoryCatalog:
        def iter_category_records(self):
            yield CategoryRecord(
                product_id=47,
                value="美容仪",
                state="known",
            )

    service, receipt, _ = _bundle()
    observer = FakeIdentityObserver(candidate_ids=(47, 24))
    catalog = _catalog()
    flow = _flow_type()(
        image_bundles=service,
        identity_observer=observer,
        category_catalog=UnsupportedCategoryCatalog(),
        decision_facts=catalog,
        presentation_facts=catalog,
        max_results=10,
    )

    events = list(flow.stream(_turn(receipt, "找相似款")))

    assert not any(event.event == "products" for event in events)
    error = next(event for event in events if event.event == "error")
    assert error.data.code == "IMAGE_CATEGORY_UNSUPPORTED"


@pytest.mark.parametrize(
    ("image_count", "message"),
    [
        (1, "100元以内找相似款"),
        (1, "这款适合敏感肌吗"),
        (2, "比较这两张图"),
        (3, "比较这些图片"),
    ],
)
def test_each_successful_image_path_advances_delivery_version(
    image_count: int,
    message: str,
) -> None:
    product_ids = (53, 55, 57, 58)[:image_count]
    service, receipt, _ = _bundle(image_count=image_count)
    catalog = _catalog()
    flow = _flow_type()(
        image_bundles=service,
        identity_observer=SequencedIdentityObserver(product_ids),
        category_catalog=catalog,
        decision_facts=catalog,
        presentation_facts=catalog,
        max_results=10,
    )

    events = list(flow.stream(_turn(receipt, message)))

    assert any(event.event == "products" for event in events)
    assert events[-1].event == "end"
    assert events[-1].data.conversation_version == 1


def test_consecutive_distinct_images_receive_monotonic_versions() -> None:
    service, first_receipt, _ = _bundle()
    second_receipt = service.create(
        session_id="session-image",
        images=[
            UntrustedImageInput(
                file_name="second-product.jpg",
                declared_media_type="image/jpeg",
                content=_jpeg((201, 33, 79)),
            )
        ],
    )
    catalog = _catalog()
    flow = _flow_type()(
        image_bundles=service,
        identity_observer=SequencedIdentityObserver((53, 55)),
        category_catalog=catalog,
        decision_facts=catalog,
        presentation_facts=catalog,
        max_results=10,
    )

    first = list(
        flow.stream(_turn(first_receipt, "这款适合敏感肌吗"))
    )
    second_turn = _turn(
        second_receipt,
        "这款适合敏感肌吗",
    ).model_copy(
        update={
            "conversation_version": (
                first[-1].data.conversation_version
            )
        }
    )
    second = list(flow.stream(second_turn))

    assert [
        next(
            event.data.cards[0].product_id
            for event in events
            if event.event == "products"
        )
        for events in (first, second)
    ] == [53, 55]
    assert [
        events[-1].data.conversation_version
        for events in (first, second)
    ] == [1, 2]


def test_image_then_text_share_authoritative_conversation_version(
    real_reader,
    real_product_assets,
) -> None:
    conversation_state = InMemoryConversationState()
    owner = ProfileOwnerRef(
        scope="anonymous_browser",
        subject_id="profile_image_text_0123456789",
    )
    service, receipt, _ = _bundle()
    catalog = _catalog()
    image_flow = _flow_type()(
        image_bundles=service,
        identity_observer=FakeIdentityObserver(),
        category_catalog=catalog,
        decision_facts=catalog,
        presentation_facts=catalog,
        conversation_state=conversation_state,
        max_results=10,
    )
    image_turn = _turn(
        receipt,
        "这款适合敏感肌吗",
    ).model_copy(update={"profile_owner": owner})

    image_events = list(image_flow.stream(image_turn))
    image_version = image_events[-1].data.conversation_version
    text_flow = compose_text_recommendation_orchestrator(
        real_reader,
        product_assets=real_product_assets,
        conversation_state=conversation_state,
    )
    text_events = list(
        text_flow.stream(
            UserTurn(
                session_id=image_turn.session_id,
                message="100元内防晒",
                conversation_version=image_version,
                profile_owner=owner,
            )
        )
    )

    assert image_events[-1].event == "end"
    assert text_events[-1].event == "end"
    assert [
        image_version,
        text_events[-1].data.conversation_version,
    ] == [1, 2]
    stored = conversation_state.load(image_turn.session_id)
    assert stored is not None
    assert stored.version == 2


def test_text_then_image_share_authoritative_conversation_version(
    real_reader,
    real_product_assets,
) -> None:
    conversation_state = InMemoryConversationState()
    owner = ProfileOwnerRef(
        scope="anonymous_browser",
        subject_id="profile_text_image_0123456789",
    )
    text_flow = compose_text_recommendation_orchestrator(
        real_reader,
        product_assets=real_product_assets,
        conversation_state=conversation_state,
    )
    text_events = list(
        text_flow.stream(
            UserTurn(
                session_id="session-image",
                message="100元内防晒",
                conversation_version=0,
                profile_owner=owner,
            )
        )
    )
    text_version = text_events[-1].data.conversation_version
    service, receipt, _ = _bundle()
    catalog = _catalog()
    image_flow = _flow_type()(
        image_bundles=service,
        identity_observer=FakeIdentityObserver(),
        category_catalog=catalog,
        decision_facts=catalog,
        presentation_facts=catalog,
        conversation_state=conversation_state,
        max_results=10,
    )
    image_turn = _turn(
        receipt,
        "这款适合敏感肌吗",
    ).model_copy(
        update={
            "conversation_version": text_version,
            "profile_owner": owner,
        }
    )

    image_events = list(image_flow.stream(image_turn))

    assert text_events[-1].event == "end"
    assert image_events[-1].event == "end"
    assert [
        text_version,
        image_events[-1].data.conversation_version,
    ] == [1, 2]
    stored = conversation_state.load(image_turn.session_id)
    assert stored is not None
    assert stored.version == 2


def test_recreated_image_flow_uses_authoritative_conversation_version() -> None:
    conversation_state = InMemoryConversationState()
    owner = ProfileOwnerRef(
        scope="anonymous_browser",
        subject_id="profile_image_restart_0123456789",
    )
    service, first_receipt, _ = _bundle()
    second_receipt = service.create(
        session_id="session-image",
        images=[
            UntrustedImageInput(
                file_name="restart-product.jpg",
                declared_media_type="image/jpeg",
                content=_jpeg((71, 109, 211)),
            )
        ],
    )
    catalog = _catalog()

    def build_flow():
        return _flow_type()(
            image_bundles=service,
            identity_observer=FakeIdentityObserver(),
            category_catalog=catalog,
            decision_facts=catalog,
            presentation_facts=catalog,
            conversation_state=conversation_state,
            max_results=10,
        )

    first_turn = _turn(
        first_receipt,
        "这款适合敏感肌吗",
    ).model_copy(update={"profile_owner": owner})
    first = list(build_flow().stream(first_turn))
    second_turn = _turn(
        second_receipt,
        "这款适合敏感肌吗",
    ).model_copy(
        update={
            "conversation_version": (
                first[-1].data.conversation_version
            ),
            "profile_owner": owner,
        }
    )

    second = list(build_flow().stream(second_turn))

    assert [
        events[-1].data.conversation_version
        for events in (first, second)
    ] == [1, 2]


def test_concurrent_image_successes_allocate_inside_session_lock() -> None:
    service, first_receipt, _ = _bundle()
    second_receipt = service.create(
        session_id="session-image",
        images=[
            UntrustedImageInput(
                file_name="concurrent-product.jpg",
                declared_media_type="image/jpeg",
                content=_jpeg((17, 211, 83)),
            )
        ],
    )
    catalog = _catalog()
    flow = _flow_type()(
        image_bundles=service,
        identity_observer=SequencedIdentityObserver((53, 55)),
        category_catalog=catalog,
        decision_facts=catalog,
        presentation_facts=catalog,
        session_locks=InMemorySessionLocks(),
        max_results=10,
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                lambda receipt: list(
                    flow.stream(
                        _turn(
                            receipt,
                            "这款适合敏感肌吗",
                        )
                    )
                ),
                (first_receipt, second_receipt),
            )
        )

    assert sorted(
        events[-1].data.conversation_version
        for events in results
    ) == [1, 2]
