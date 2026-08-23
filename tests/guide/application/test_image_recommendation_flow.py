from __future__ import annotations

from hashlib import sha256
import importlib
import inspect
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
from app.guide.application.contracts import TurnIdentity, UserTurn
from app.guide.application.dynamic_consultation import (
    PreparedConsultationEvidence,
)
from app.guide.application.execution_contracts import (
    ExecutionResult,
    OpaqueRetrievalQuery,
    PreRoutingEvidence,
    PresentationTerminal,
    ProcessorExecutionInput,
)
from app.guide.application.image_bundle_service import ImageBundleService
from app.guide.feedback.profile_policy import ResolvedProfileContext
from app.guide.intent.executable_intent_compiler import (
    compile_turn_meaning,
)
from app.guide.intent.responsibility_matrix import Responsibility
from app.guide.intent.task_planning import plan_task
from app.guide.intent.unified_turn_router import UnifiedRouteDecision
from app.guide.retrieval.product_name_resolver import (
    ProductMentionResolution,
    ResolvedProductBinding,
)
from app.guide.understanding.image_contracts import (
    IdentityEvidenceConsistency,
    IdentityState,
    ImageIdentityObservation,
    ObservationState,
    OcrObservationState,
    VisualObservationState,
)
from app.guide.understanding.turn_meaning_contracts import TurnMeaning
from app.guide.understanding.semantic_contracts import (
    SemanticContext,
)




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






def test_prepare_routing_evidence_observes_each_authorized_image_once() -> None:
    service, receipt, _ = _bundle(image_count=2)
    observer = SequencedIdentityObserver((53, 55))
    catalog = _catalog()
    flow = _flow_type()(
        image_bundles=service,
        identity_observer=observer,
        category_catalog=catalog,
        decision_facts=catalog,
        presentation_facts=catalog,
    )
    turn = _turn(receipt, "比较这两张图")
    prepare = getattr(flow, "prepare_routing_evidence", None)

    assert callable(prepare)
    evidence = prepare(turn)
    assert evidence.bundle.bundle_id == receipt.bundle_id
    assert [item.ordinal for item in evidence.payloads] == [1, 2]
    assert [item.confirmed_product_id for item in evidence.observations] == [
        53,
        55,
    ]
    assert [item.product_id for item in evidence.confirmed_products] == [
        53,
        55,
    ]
    assert evidence.anchor_topic is None
    assert len(observer.requests) == 2


def test_image_identity_execute_returns_result_without_state_write() -> None:
    service, receipt, _ = _bundle(image_count=1)
    observer = FakeIdentityObserver(candidate_ids=(53, 55, 57))
    catalog = _catalog()
    state = InMemoryConversationState()
    flow = _flow_type()(
        image_bundles=service,
        identity_observer=observer,
        category_catalog=catalog,
        decision_facts=catalog,
        presentation_facts=catalog,
    )
    turn = _turn(receipt, "这是什么商品")
    evidence = flow.prepare_routing_evidence(turn)
    meaning = _image_meaning("image_identity")
    understanding = compile_turn_meaning(
        message=turn.message,
        meaning=meaning,
        context=SemanticContext(
            conversation_version=0,
            active_topic=None,
            visible_candidate_count=0,
            image_count=1,
            focused_image_ordinal=1,
            confirmed_profile_fields=(),
        ),
    )
    decision = UnifiedRouteDecision(
        processor="image_identity",
        responsibility=Responsibility.IMAGE_IDENTITY,
        presentation_mode="image_identity",
        continuity="replace_task",
        focus_source="confirmed_image",
        product_bindings=(
            ResolvedProductBinding(
                product_id=53,
                source_text="image_ordinal:1",
            ),
        ),
    )

    execution_input = ProcessorExecutionInput(
        turn_identity=turn.identity,
        understanding=understanding,
        decision=decision,
        current_snapshot=None,
        routing_evidence=PreRoutingEvidence(
            query=OpaqueRetrievalQuery(value=turn.question_summary),
            conversation_version=turn.conversation_version,
            profile_context=ResolvedProfileContext(values=()),
            product_resolution=ProductMentionResolution(bindings=()),
            task_plan=plan_task(
                understanding,
                responsibility=decision.responsibility,
                resolved_product_ids=(53,),
                message=turn.message,
            ),
            consultation=PreparedConsultationEvidence(),
            image=evidence,
            candidate_product_ids=(53, 55, 57),
        ),
    )

    result = flow.execute(execution_input)

    assert type(result) is ExecutionResult
    assert result.decision is decision
    assert isinstance(result.terminal, PresentationTerminal)
    assert result.terminal.data.mode == "image_identity"
    assert result.state_delta.image.action == "replace"
    assert [
        item.product_id
        for item in result.state_delta.image.value.confirmed_products
    ] == [53]
    assert state.load(turn.session_id) is None
    assert len(observer.requests) == 1


def test_image_processor_has_no_legacy_stream_or_state_owner() -> None:
    processor = _flow_type()
    source = inspect.getsource(processor)

    assert not hasattr(processor, "stream")
    assert not hasattr(processor, "stream_understanding")
    assert "_conversation_state" not in source
    assert "_session_locks" not in source
    assert "_delivery_versions" not in source
    assert "_success_end" not in source


def test_trace_identity_request_delegates_without_streaming_events() -> None:
    service, receipt, _ = _bundle()
    payload = service.authorize_payloads(
        bundle_id=receipt.bundle_id,
        version=receipt.version,
        session_id="session-image",
        owner_token=receipt.owner_token,
    )[0]
    observer = FakeIdentityObserver()
    expected_observation = observer.observe(
        SimpleNamespace(
            image_id=payload.image_id,
            content=payload.content,
            max_results=10,
        )
    )
    expected_trace = object()
    observer.requests.clear()
    observer.observe_with_trace = lambda request: (
        expected_observation,
        expected_trace,
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
    request = SimpleNamespace(
        image_id=payload.image_id,
        content=payload.content,
        max_results=10,
    )

    result = flow.trace_identity_request(request)

    assert result == (expected_observation, expected_trace)


def _turn(receipt, message: str) -> UserTurn:
    identity_digest = sha256(
        f"session-image\0{receipt.version}\0{receipt.bundle_id}\0{message}".encode()
    ).hexdigest()
    return UserTurn(
        identity=TurnIdentity(
            session_id="session-image",
            request_id=f"request_{identity_digest}",
            turn_id=f"turn_{identity_digest}",
        ),
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
            "recommendation_mode": (
                "explore"
                if operation == "image_similarity"
                else None
            ),
            "recommendation_mode_basis": (
                {
                    "basis": "similar_alternatives",
                    "source_text": "相似",
                }
                if operation == "image_similarity"
                else None
            ),
            "recommendation_count": (
                3 if operation == "image_similarity" else None
            ),
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
