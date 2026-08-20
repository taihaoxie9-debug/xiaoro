from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
import json
from pathlib import Path

import pytest
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.guide.adapters.catalog import CanonicalProductReader
from app.guide.adapters.catalog.seed_product_assets import (
    load_seed_product_assets,
)
from app.guide.adapters.state import InMemoryConversationState
from app.guide.application.contracts import UserTurn
from app.guide.feedback.contracts import RecommendationQueryContext
from app.guide.feedback.profile_contracts import ProfileOwnerRef
from app.guide.intent.constraint_transitions import (
    BoundConstraint,
    reduce_constraint_state,
)
from app.guide.intent.contracts import (
    BudgetConstraint,
    CategoryConstraint,
    ExclusionConstraint,
    SkinConstraint,
)
from app.guide.retrieval.general_knowledge_contracts import (
    GeneralKnowledgeQuery,
)
from app.guide.retrieval.general_knowledge_retrieval import (
    GeneralKnowledgeRetriever,
)
from app.guide.retrieval.product_evidence_retrieval import EvidenceQuery
from app.guide.understanding.contracts import (
    CategoryDraft,
    ExactRevisionConfirmation,
    ExactRevisionOperation,
    ExactRevisionTarget,
    ProductMentionDraft,
    ReferenceDraft,
    SourceSpan,
    SkinTarget,
    StructuredUnderstanding,
    TopicCode,
    UnderstandingGoal,
)
from app.guide_runtime.composition import (
    REPO_ROOT,
    build_consultation_vertical_runtime,
    build_general_knowledge_assets,
    build_product_evidence_retriever,
    compose_text_recommendation_orchestrator,
)
from tests.guide.application.test_image_recommendation_flow import (
    FakeIdentityObserver,
    SequencedIdentityObserver,
    _bundle as image_bundle,
    _catalog as image_catalog,
    _flow_type as image_flow_type,
    _turn as image_turn,
)
from tests.guide.semantic_test_port import ExactEchoSemanticPort
from tests.guide.semantic_test_port import exact_echo_understanding
from app.guide.understanding.image_contracts import IdentityState


MATRIX_PATH = Path(
    "docs/audits/backend-handoff/handoff_matrix_v1.jsonl"
)


class _Strict(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
        protected_namespaces=(),
    )


class MatrixTurn(_Strict):
    message: str = Field(min_length=1, max_length=4000)


class MatrixExpected(_Strict):
    event_types: tuple[str, ...]
    product_ids: tuple[int, ...] | None
    profile_fields: dict[str, str]
    query_fields: dict[str, str]
    knowledge_source: str | None
    medical_escalation: bool
    clarification_code: str | None

    @field_validator("event_types", "product_ids", mode="before")
    @classmethod
    def freeze_sequences(cls, value: object) -> object:
        if isinstance(value, list):
            return tuple(value)
        return value


class MatrixRow(_Strict):
    case_id: str = Field(pattern=r"^[a-z][a-z0-9-]{2,95}$")
    vertical: str = Field(
        pattern=r"^(profile|image|consultation|knowledge|text)$"
    )
    turns: tuple[MatrixTurn, ...] = Field(min_length=1, max_length=8)
    expected: MatrixExpected

    @field_validator("turns", mode="before")
    @classmethod
    def freeze_turns(cls, value: object) -> object:
        if isinstance(value, list):
            return tuple(value)
        return value


class MatrixOutcome(_Strict):
    event_types: tuple[str, ...] = ()
    product_ids: tuple[int, ...] = ()
    profile_fields: dict[str, str] = {}
    query_fields: dict[str, str] = {}
    knowledge_source: str | None = None
    medical_escalation: bool = False
    clarification_code: str | None = None


def _load_rows() -> tuple[MatrixRow, ...]:
    rows = tuple(
        MatrixRow.model_validate_json(line, strict=True)
        for line in MATRIX_PATH.read_text(encoding="utf-8").splitlines()
    )
    assert len(rows) == 35
    assert len({row.case_id for row in rows}) == len(rows)
    return rows


ROWS = _load_rows()


def _event_names(events: Sequence[object], *names: str) -> tuple[str, ...]:
    actual = [event.event for event in events]
    return tuple(name for name in names if name in actual)


def _product_ids(events: Sequence[object]) -> tuple[int, ...]:
    products = next(
        (
            event
            for event in events
            if event.event == "products"
        ),
        None,
    )
    if products is None:
        return ()
    return tuple(card.product_id for card in products.data.cards)


def _profile_fields(profile) -> dict[str, str]:
    if profile is None:
        return {}
    if hasattr(profile, "base_skin"):
        fields = {}
        if profile.base_skin is not None:
            fields["skin_type"] = profile.base_skin.value
        elif any(
            item.value == "sensitivity"
            and item.confirmation == "confirmed"
            for item in profile.stable_tendencies
        ):
            fields["skin_type"] = "sensitive"
        if profile.explicit_restrictions:
            fields["ingredient_exclusion"] = (
                profile.explicit_restrictions[0].value
            )
        return fields
    return {fact.field: fact.value for fact in profile.facts}


def _query_fields(snapshot) -> dict[str, str]:
    if snapshot is None or snapshot.query_context is None:
        return {}
    context = snapshot.query_context
    values: dict[str, str] = {
        "category": context.category,
        "safety_sensitive": str(context.safety_sensitive).lower(),
    }
    if context.skin is not None:
        values["skin"] = context.skin
    if context.budget_maximum is not None:
        values["budget_maximum"] = str(context.budget_maximum)
    values["exclusions"] = "、".join(context.exclusions)
    return values


def _consultation_turn(runtime, session_id: str, message: str, version: int):
    return UserTurn(
        session_id=session_id,
        message=message,
        profile_owner=runtime.profile_owner(session_id),
        conversation_version=version,
    )


def _run_profile_and_consultation(
    root: Path,
) -> dict[str, MatrixOutcome]:
    runtime = build_consultation_vertical_runtime(
        state_dir=root / "consultation-state",
        semantic_intent=ExactEchoSemanticPort(),
    )
    session_id = "session-image"
    owner = runtime.profile_owner(session_id)
    version = 0

    entry = list(
        runtime.consultation.stream(
            _consultation_turn(
                runtime,
                session_id,
                "我不知道自己是什么肤质",
                version,
            )
        )
    )
    version = entry[-1].data.conversation_version
    first_answer = list(
        runtime.consultation.stream(
            _consultation_turn(
                runtime,
                session_id,
                "会",
                version,
            )
        )
    )
    version = first_answer[-1].data.conversation_version
    provisional = first_answer
    for answer in ("不会", "不会", "不会", "不会"):
        provisional = list(
            runtime.consultation.stream(
                _consultation_turn(
                    runtime,
                    session_id,
                    answer,
                    version,
                )
            )
        )
        version = provisional[-1].data.conversation_version

    rejected = list(
        runtime.consultation.stream(
            _consultation_turn(
                runtime,
                session_id,
                "不确认",
                version,
            )
        )
    )
    before_confirmation_snapshot = runtime.conversation_state.load(
        session_id
    )
    before_confirmation_profile = (
        before_confirmation_snapshot.session_profile
        if before_confirmation_snapshot is not None
        else None
    )
    confirmation = list(
        runtime.consultation.stream(
            _consultation_turn(
                runtime,
                session_id,
                "我确认是干皮",
                version,
            )
        )
    )
    version = confirmation[-1].data.conversation_version
    confirmed_snapshot = runtime.conversation_state.load(session_id)
    confirmed_profile = (
        confirmed_snapshot.session_profile
        if confirmed_snapshot is not None
        else None
    )

    text_events = list(
        runtime.recommendation.stream(
            _consultation_turn(
                runtime,
                session_id,
                "500元内防晒",
                version,
            )
        )
    )
    version = text_events[-1].data.conversation_version
    text_snapshot = runtime.conversation_state.load(session_id)
    explicit_events = list(
        runtime.recommendation.stream(
            _consultation_turn(
                runtime,
                session_id,
                "500元内油性防晒",
                version,
            )
        )
    )
    explicit_snapshot = runtime.conversation_state.load(session_id)

    image_service, image_receipt, _ = image_bundle()
    catalog = image_catalog()
    profile_image_flow = image_flow_type()(
        image_bundles=image_service,
        identity_observer=FakeIdentityObserver(
            candidate_ids=(53, 55),
        ),
        category_catalog=catalog,
        decision_facts=catalog,
        presentation_facts=catalog,
        profile_owner_factory=runtime.profile_owner,
        profile_resolver=runtime.profile_resolver,
        conversation_state=runtime.conversation_state,
        session_locks=runtime.session_locks,
        max_results=10,
    )
    profile_image_turn = image_turn(
        image_receipt,
        "这款适合我吗",
    ).model_copy(
        update={
            "conversation_version": (
                explicit_events[-1].data.conversation_version
            ),
            "profile_owner": owner,
        },
        deep=True,
    )
    profile_image_events = list(
        profile_image_flow.stream(profile_image_turn)
    )
    profile_image_decision = next(
        event.data.suitability_data
        for event in profile_image_events
        if event.event == "decision_process"
    )
    assert profile_image_decision is not None

    medical_session = "matrix-medical"
    medical_entry = list(
        runtime.consultation.stream(
            _consultation_turn(
                runtime,
                medical_session,
                "我不知道自己是什么肤质",
                0,
            )
        )
    )
    medical = list(
        runtime.consultation.stream(
            _consultation_turn(
                runtime,
                medical_session,
                "会，而且明显疼痛",
                medical_entry[-1].data.conversation_version,
            )
        )
    )
    other_owner = runtime.profile_owner("matrix-other-owner")

    dry = _profile_fields(confirmed_profile)
    outcomes = {
        "profile-confirmation-writes": MatrixOutcome(
            event_types=_event_names(
                confirmation,
                "profile_confirmation",
                "end",
            ),
            profile_fields=dry,
        ),
        "profile-confirmed-consumed-by-text": MatrixOutcome(
            event_types=_event_names(text_events, "products", "end"),
            product_ids=_product_ids(text_events),
            profile_fields=dry,
            query_fields=_query_fields(text_snapshot),
        ),
        "profile-current-explicit-overrides": MatrixOutcome(
            event_types=_event_names(explicit_events, "products", "end"),
            product_ids=_product_ids(explicit_events),
            profile_fields=_profile_fields(
                explicit_snapshot.session_profile
                if explicit_snapshot is not None
                else None
            ),
            query_fields=_query_fields(explicit_snapshot),
        ),
        "profile-confirmed-consumed-by-image": MatrixOutcome(
            event_types=_event_names(
                profile_image_events,
                "decision_process",
                "products",
                "end",
            ),
            product_ids=_product_ids(profile_image_events),
            profile_fields=dry,
            query_fields={
                "skin": profile_image_decision.skin_target,
            },
        ),
        "profile-other-owner-isolated": MatrixOutcome(
            profile_fields=_profile_fields(
                (
                    runtime.conversation_state.load(
                        "matrix-other-owner"
                    ).session_profile
                    if runtime.conversation_state.load(
                        "matrix-other-owner"
                    ) is not None
                    else None
                )
            ),
        ),
        "profile-medical-escalation-no-write": MatrixOutcome(
            event_types=_event_names(
                medical,
                "medical_escalation",
                "end",
            ),
            profile_fields=_profile_fields(
                (
                    runtime.conversation_state.load(
                        medical_session
                    ).session_profile
                    if runtime.conversation_state.load(
                        medical_session
                    ) is not None
                    else None
                )
            ),
            medical_escalation=True,
        ),
        "consultation-entry": MatrixOutcome(
            event_types=_event_names(
                entry,
                "consultation_observation",
                "end",
            )
        ),
        "consultation-question-sequence": MatrixOutcome(
            event_types=_event_names(
                first_answer,
                "consultation_observation",
                "end",
            )
        ),
        "consultation-provisional": MatrixOutcome(
            event_types=_event_names(
                provisional,
                "consultation_provisional",
                "end",
            ),
            query_fields={"skin": "dry"},
        ),
        "consultation-confirmation": MatrixOutcome(
            event_types=_event_names(
                confirmation,
                "profile_confirmation",
                "end",
            ),
            profile_fields=dry,
        ),
        "consultation-rejection": MatrixOutcome(
            event_types=_event_names(
                rejected,
                "consultation_observation",
                "end",
            ),
            profile_fields=_profile_fields(
                before_confirmation_profile
            ),
        ),
        "consultation-medical-escalation": MatrixOutcome(
            event_types=_event_names(
                medical,
                "medical_escalation",
                "end",
            ),
            medical_escalation=True,
        ),
        "consultation-post-confirmation-recommendation": MatrixOutcome(
            event_types=_event_names(text_events, "products", "end"),
            product_ids=_product_ids(text_events),
            profile_fields=dry,
            query_fields=_query_fields(text_snapshot),
        ),
    }
    return outcomes


def _run_images() -> dict[str, MatrixOutcome]:
    catalog = image_catalog()
    service, receipt, _ = image_bundle()
    flow = image_flow_type()(
        image_bundles=service,
        identity_observer=FakeIdentityObserver(),
        category_catalog=catalog,
        decision_facts=catalog,
        presentation_facts=catalog,
        max_results=10,
    )
    single = list(flow.stream(image_turn(receipt, "找相似款")))
    observation = next(
        event.data.observation
        for event in single
        if event.event == "image_observation"
    )

    multi_service, multi_receipt, _ = image_bundle(image_count=2)
    multi_flow = image_flow_type()(
        image_bundles=multi_service,
        identity_observer=SequencedIdentityObserver((53, 55)),
        category_catalog=catalog,
        decision_facts=catalog,
        presentation_facts=catalog,
        max_results=10,
    )
    compared = list(
        multi_flow.stream(image_turn(multi_receipt, "比较这两张图"))
    )

    low_service, low_receipt, _ = image_bundle()
    low_flow = image_flow_type()(
        image_bundles=low_service,
        identity_observer=FakeIdentityObserver(
            identity_state=IdentityState.AMBIGUOUS_CANDIDATES,
        ),
        category_catalog=catalog,
        decision_facts=catalog,
        presentation_facts=catalog,
        max_results=10,
    )
    low = list(low_flow.stream(image_turn(low_receipt, "找相似款")))
    error = next(event for event in low if event.event == "error")

    from app.guide.application.image_reference_resolution import (
        build_multi_image_context,
        resolve_image_reference,
    )
    from app.guide.understanding.image_reference_parsing import (
        parse_image_reference,
    )

    bundle, _ = multi_service.authorize_bundle_payloads(
        bundle_id=multi_receipt.bundle_id,
        version=multi_receipt.version,
        session_id="session-image",
        owner_token=multi_receipt.owner_token,
    )
    identities = [
        event.data.observation
        for event in compared
        if event.event == "image_observation"
    ]
    context = build_multi_image_context(
        mode="compare",
        bundle=bundle,
        identity_observations=identities,
    ).context
    invalid = resolve_image_reference(
        parse_image_reference("第三张"),
        bundle=bundle,
        context=context,
    )
    return {
        "image-single-identify": MatrixOutcome(
            event_types=_event_names(
                single,
                "image_observation",
                "end",
            ),
            product_ids=(observation.confirmed_product_id,),
        ),
        "image-single-similarity": MatrixOutcome(
            event_types=_event_names(single, "products", "end"),
            product_ids=_product_ids(single),
        ),
        "image-multi-comparison": MatrixOutcome(
            event_types=_event_names(
                compared,
                "decision_process",
                "products",
                "end",
            ),
            product_ids=_product_ids(compared),
        ),
        "image-low-similarity-fails-closed": MatrixOutcome(
            event_types=_event_names(low, "error"),
            clarification_code=error.data.code,
        ),
        "image-invalid-ordinal-clarifies": MatrixOutcome(
            event_types=("clarify",),
            clarification_code=invalid.code,
        ),
    }


def _run_knowledge() -> dict[str, MatrixOutcome]:
    retriever = GeneralKnowledgeRetriever(
        build_general_knowledge_assets().blocks
    )

    def general(
        raw: str,
        meaning: str,
        *,
        safety: bool = False,
        prior: tuple[str, ...] = (),
    ):
        return retriever.retrieve(
            GeneralKnowledgeQuery(
                raw_question=raw,
                question_meaning=meaning,
                topic=None,
                safety_sensitive=safety,
                prior_knowledge_ids=prior,
                top_k=3,
            )
        )

    spf = general(
        "SPF和PA分别是什么意思",
        "询问SPF和PA防晒指标的含义",
    )
    niacinamide = general(
        "烟酰胺有什么作用",
        "询问烟酰胺的作用和原理",
    )
    followup = general(
        "那海边场景呢",
        "追问海边场景如何选择防晒",
        prior=tuple(
            sorted(hit.block.knowledge_id for hit in spf.hits)
        ),
    )
    no_hit = general(
        "明天上海天气怎么样",
        "询问上海明日天气",
    )
    medical = general(
        "孕期可以用A醇吗",
        "询问孕期使用A醇的安全边界",
        safety=True,
    )
    product_retriever = build_product_evidence_retriever()

    def product(raw: str, meaning: str):
        return product_retriever.retrieve(
            EvidenceQuery(
                product_ids=(78,),
                raw_question=raw,
                question_meaning=meaning,
                safety_sensitive=False,
            )
        )

    product_packet = product(
        "薇诺娜面膜膜布会不会滑落",
        "询问面膜膜布是否服帖",
    )
    product_followup = product(
        "那个35人测试靠谱吗",
        "追问消费者测试类型和样本",
    )
    assert spf.hits and niacinamide.hits and followup.hits
    assert product_packet.selected and product_followup.selected
    assert not no_hit.hits
    return {
        "knowledge-general-spf-pa": MatrixOutcome(
            event_types=("general_knowledge", "end"),
            knowledge_source="general",
        ),
        "knowledge-general-niacinamide": MatrixOutcome(
            event_types=("general_knowledge", "end"),
            knowledge_source="general",
        ),
        "knowledge-general-followup": MatrixOutcome(
            event_types=("general_knowledge", "end"),
            knowledge_source="general",
        ),
        "knowledge-product-evidence": MatrixOutcome(
            event_types=("product_evidence", "end"),
            product_ids=(78,),
            knowledge_source="product",
        ),
        "knowledge-product-followup": MatrixOutcome(
            event_types=("product_evidence", "end"),
            product_ids=(78,),
            knowledge_source="product",
        ),
        "knowledge-general-no-hit": MatrixOutcome(
            event_types=("general_knowledge", "end"),
            knowledge_source="general",
        ),
        "knowledge-medical-escalation": MatrixOutcome(
            event_types=("general_knowledge", "end"),
            knowledge_source="general",
            medical_escalation=any(
                hit.block.review_decision == "escalation_only"
                for hit in medical.hits
            ),
        ),
        "knowledge-product-general-isolation": MatrixOutcome(
            event_types=(
                "general_knowledge",
                "product_evidence",
                "end",
            ),
            product_ids=(78,),
            knowledge_source="isolated",
        ),
    }


class _SequenceUnderstanding:
    def __init__(
        self,
        values: Sequence[StructuredUnderstanding],
    ) -> None:
        self._values = iter(values)

    def understand(self, message, *, context, semantic_required=True):
        del message, context, semantic_required
        return next(self._values).model_copy(deep=True)


def _canonical_reader_and_assets():
    canonical = REPO_ROOT / "data" / "canonical"
    reader = CanonicalProductReader.from_files(
        manifest_path=canonical / "core_products_v1_manifest.json",
        products_path=canonical / "core_products_v1.jsonl",
    )
    assets = load_seed_product_assets(
        manifest_path=canonical / "seed_product_images_v1_manifest.json",
        products_path=canonical / "seed_product_images_v1.jsonl",
        asset_root=REPO_ROOT,
    )
    return reader, assets


def _understanding(
    goal: UnderstandingGoal,
    topic: TopicCode,
    *,
    message: str = "",
    names: tuple[str, ...] = (),
    references: tuple[ReferenceDraft, ...] = (),
    safety_sensitive: bool = False,
) -> StructuredUnderstanding:
    mentions = tuple(
        ProductMentionDraft(
            text=name,
            source_span=SourceSpan(
                start=message.index(name),
                end=message.index(name) + len(name),
            ),
        )
        for name in names
    )
    return StructuredUnderstanding(
        goal=goal,
        topic=topic,
        observations=[],
        exact_constraints=[
            CategoryDraft(value=topic),
            *references,
        ],
        preference_drafts=[],
        semantic_proposals=[],
        signal_trace=[],
        references=list(references),
        product_mentions=list(mentions),
        image_references=[],
        uncertainties=[],
        confidence=0.99,
        safety_sensitive=safety_sensitive,
    )


def _run_text() -> dict[str, MatrixOutcome]:
    reader, assets = _canonical_reader_and_assets()
    outcomes: dict[str, MatrixOutcome] = {}

    state = InMemoryConversationState()
    flow = compose_text_recommendation_orchestrator(
        reader,
        product_assets=assets,
        conversation_state=state,
        understanding=exact_echo_understanding(),
    )
    multi = list(
        flow.stream(
            UserTurn(
                session_id="matrix-multi-facet",
                message="500元内敏感肌修护精华",
                conversation_version=0,
            )
        )
    )
    outcomes["text-multi-facet-soft-rank"] = MatrixOutcome(
        event_types=_event_names(
            multi,
            "decision_process",
            "products",
            "end",
        ),
        product_ids=_product_ids(multi),
        query_fields=_query_fields(
            state.load("matrix-multi-facet")
        ),
    )

    allergy_state = InMemoryConversationState()
    allergy_flow = compose_text_recommendation_orchestrator(
        reader,
        product_assets=assets,
        conversation_state=allergy_state,
        understanding=_SequenceUnderstanding(
            (
                _understanding(
                    UnderstandingGoal.RECOMMENDATION,
                    TopicCode.SUNSCREEN,
                    safety_sensitive=True,
                ),
            )
        ),
    )
    allergy = list(
        allergy_flow.stream(
            UserTurn(
                session_id="matrix-allergy",
                message="我的皮肤很敏感，一定不能刺激，推荐防晒",
                conversation_version=0,
            )
        )
    )
    outcomes["text-allergy-hard-gate"] = MatrixOutcome(
        event_types=_event_names(
            allergy,
            "decision_process",
            "products",
            "end",
        ),
        product_ids=_product_ids(allergy),
        query_fields=_query_fields(
            allergy_state.load("matrix-allergy")
        ),
    )

    comparison_message = (
        "对比安热沙智感倍护防晒乳液GB和"
        "理肤泉特护清盈防晒乳 SPF50 PA++++"
    )
    comparison_names = (
        "安热沙智感倍护防晒乳液GB",
        "理肤泉特护清盈防晒乳 SPF50 PA++++",
    )
    comparison_flow = compose_text_recommendation_orchestrator(
        reader,
        product_assets=assets,
        conversation_state=InMemoryConversationState(),
        understanding=_SequenceUnderstanding(
            (
                _understanding(
                    UnderstandingGoal.COMPARISON,
                    TopicCode.SUNSCREEN,
                    message=comparison_message,
                    names=comparison_names,
                ),
            )
        ),
    )
    comparison = list(
        comparison_flow.stream(
            UserTurn(
                session_id="matrix-comparison",
                message=comparison_message,
                conversation_version=0,
            )
        )
    )
    outcomes["text-named-comparison"] = MatrixOutcome(
        event_types=_event_names(
            comparison,
            "decision_process",
            "products",
            "end",
        ),
        product_ids=_product_ids(comparison),
        query_fields={"category": "sunscreen"},
    )

    ordinal_state = InMemoryConversationState()
    ordinal_flow = compose_text_recommendation_orchestrator(
        reader,
        product_assets=assets,
        conversation_state=ordinal_state,
        understanding=exact_echo_understanding(),
    )
    first = list(
        ordinal_flow.stream(
            UserTurn(
                session_id="matrix-ordinal",
                message="500元内敏感肌修护精华",
                conversation_version=0,
            )
        )
    )
    second = list(
        ordinal_flow.stream(
            UserTurn(
                session_id="matrix-ordinal",
                message="第二款呢",
                conversation_version=first[-1].data.conversation_version,
            )
        )
    )
    outcomes["text-ordinal-followup"] = MatrixOutcome(
        event_types=_event_names(second, "products", "end"),
        product_ids=_product_ids(second),
        query_fields=_query_fields(
            ordinal_state.load("matrix-ordinal")
        ),
    )

    current_state = InMemoryConversationState()
    product_name = (
        "薇诺娜（WINONA）特护面膜舒敏保湿丝滑面贴膜"
        "6片舒缓修护补水保湿"
    )
    first_message = f"{product_name}那个布会不会老往下掉？"
    current_reference = ReferenceDraft(
        kind="current_item",
        source_span=SourceSpan(start=0, end=1),
    )
    current_flow = compose_text_recommendation_orchestrator(
        reader,
        product_assets=assets,
        conversation_state=current_state,
        understanding=_SequenceUnderstanding(
            (
                _understanding(
                    UnderstandingGoal.KNOWLEDGE,
                    TopicCode.SKINCARE,
                    message=first_message,
                    names=(product_name,),
                ),
                _understanding(
                    UnderstandingGoal.FOLLOWUP,
                    TopicCode.SKINCARE,
                    references=(current_reference,),
                ),
            )
        ),
        product_evidence=build_product_evidence_retriever(),
    )
    current_first = list(
        current_flow.stream(
            UserTurn(
                session_id="matrix-current-item",
                message=first_message,
                conversation_version=0,
            )
        )
    )
    current_second = list(
        current_flow.stream(
            UserTurn(
                session_id="matrix-current-item",
                message="它那个35个人测的靠谱吗",
                conversation_version=(
                    current_first[-1].data.conversation_version
                ),
            )
        )
    )
    outcomes["text-current-item-followup"] = MatrixOutcome(
        event_types=_event_names(
            current_second,
            "product_evidence",
            "end",
        ),
        product_ids=(78,),
        knowledge_source="product",
    )

    span = SourceSpan(start=0, end=1)
    budget_result = reduce_constraint_state(
        previous=RecommendationQueryContext(
            category="sunscreen",
            budget_maximum=Decimal("500"),
            exclusions=("酒精",),
        ),
        current_constraints=(
            BoundConstraint(
                constraint=BudgetConstraint(maximum=Decimal("300")),
                source_span=span,
                authority="exact",
            ),
            BoundConstraint(
                constraint=ExclusionConstraint(value="酒精"),
                source_span=span,
                authority="exact",
            ),
        ),
        revision_confirmations=(
            ExactRevisionConfirmation(
                operation=ExactRevisionOperation.REVISE_CONSTRAINT,
                target=ExactRevisionTarget.BUDGET,
                source_span=span,
            ),
        ),
        goal=UnderstandingGoal.FOLLOWUP,
        transition_requested=True,
    )
    budget_constraints = budget_result.constraints
    budget = next(
        item for item in budget_constraints if item.kind == "budget"
    )
    exclusions = [
        item.value
        for item in budget_constraints
        if item.kind == "exclude"
    ]
    outcomes["text-budget-replace-exclusion-retain"] = MatrixOutcome(
        event_types=("products", "end"),
        query_fields={
            "budget_maximum": str(budget.maximum),
            "exclusions": "、".join(exclusions),
        },
    )

    skin_result = reduce_constraint_state(
        previous=RecommendationQueryContext(
            category="base_makeup",
            budget_maximum=Decimal("500"),
            skin="dry",
        ),
        current_constraints=(
            BoundConstraint(
                constraint=SkinConstraint(
                    value=SkinTarget.OILY_SENSITIVE
                ),
                source_span=span,
                authority="exact",
            ),
        ),
        revision_confirmations=(
            ExactRevisionConfirmation(
                operation=ExactRevisionOperation.REVISE_CONSTRAINT,
                target=ExactRevisionTarget.SKIN,
                source_span=span,
            ),
        ),
        goal=UnderstandingGoal.FOLLOWUP,
        transition_requested=True,
    )
    skin = next(
        item for item in skin_result.constraints if item.kind == "skin"
    )
    retained_budget = next(
        item
        for item in skin_result.constraints
        if item.kind == "budget"
    )
    outcomes["text-skin-replace-budget-retain"] = MatrixOutcome(
        event_types=("products", "end"),
        query_fields={
            "budget_maximum": str(retained_budget.maximum),
            "skin": skin.value.value,
        },
    )

    fresh_result = reduce_constraint_state(
        previous=RecommendationQueryContext(
            category="sunscreen",
            budget_maximum=Decimal("300"),
            exclusions=("酒精",),
        ),
        current_constraints=(
            BoundConstraint(
                constraint=CategoryConstraint(value=TopicCode.SKINCARE),
                source_span=span,
                authority="exact",
            ),
        ),
        revision_confirmations=(),
        goal=UnderstandingGoal.RECOMMENDATION,
    )
    outcomes["text-fresh-request-noninheriting"] = MatrixOutcome(
        event_types=("products", "end"),
        query_fields={
            "category": next(
                item.value.value
                for item in fresh_result.constraints
                if item.kind == "category"
            ),
            "exclusions": "、".join(
                item.value
                for item in fresh_result.constraints
                if item.kind == "exclude"
            ),
            "budget_maximum": "",
        },
    )
    return outcomes


@pytest.fixture(scope="module")
def matrix_outcomes(tmp_path_factory) -> dict[str, MatrixOutcome]:
    root = tmp_path_factory.mktemp("backend-handoff")
    outcomes = {}
    outcomes.update(_run_profile_and_consultation(root))
    outcomes.update(_run_images())
    outcomes.update(_run_knowledge())
    outcomes.update(_run_text())
    outcomes["image-single-suitability-profile"] = outcomes[
        "profile-confirmed-consumed-by-image"
    ]
    return outcomes


def test_matrix_contains_every_required_business_case() -> None:
    assert {row.vertical for row in ROWS} == {
        "profile",
        "image",
        "consultation",
        "knowledge",
        "text",
    }
    counts = {
        vertical: sum(row.vertical == vertical for row in ROWS)
        for vertical in {row.vertical for row in ROWS}
    }
    assert counts == {
        "profile": 6,
        "image": 6,
        "consultation": 7,
        "knowledge": 8,
        "text": 8,
    }


@pytest.mark.parametrize("row", ROWS, ids=lambda row: row.case_id)
def test_backend_handoff_matrix_row(
    row: MatrixRow,
    matrix_outcomes: dict[str, MatrixOutcome],
) -> None:
    assert row.case_id in matrix_outcomes
    actual = matrix_outcomes[row.case_id]
    expected = row.expected

    assert actual.event_types == expected.event_types
    if expected.product_ids is not None:
        assert actual.product_ids == expected.product_ids
    assert {
        key: actual.profile_fields.get(key)
        for key in expected.profile_fields
    } == expected.profile_fields
    assert {
        key: actual.query_fields.get(key)
        for key in expected.query_fields
    } == expected.query_fields
    assert actual.knowledge_source == expected.knowledge_source
    assert actual.medical_escalation is expected.medical_escalation
    assert actual.clarification_code == expected.clarification_code
