from decimal import Decimal
from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from app.guide.presentation.contracts import (
    CardDisplayContract,
    ProductCard,
)
from app.guide.presentation.public_contracts import (
    PublicPresentationContract,
)
from app.guide.presentation.public_language import validate_public_text
from app.guide.presentation.public_language_policy import (
    validate_final_public_text,
)
from app.guide.decision.contracts import RelativeComparisonResult
from app.guide.feedback.profile_policy import (
    ProfilePersistencePlan,
    ProfilePersistenceRetry,
)
from app.guide.feedback.session_profile import SessionProfile
from app.guide.feedback.contracts import PendingTurn
from app.guide.intent.contracts import PublicIntentMode
from app.guide.retrieval.pitfall_contracts import TypedPitfall
from app.guide.retrieval.review_contracts import ReviewReadResult
from app.guide.retrieval.review_summary_contracts import (
    ReviewSummaryResult,
)
from app.guide.retrieval.category_profiles import CategoryProfile
from app.guide.retrieval.scenario_contracts import (
    ScenarioEvidenceRecord,
)
from app.guide.retrieval.product_evidence_retrieval import EvidencePacket
from app.guide.understanding.image_contracts import (
    ImageIdentityObservation,
)
from app.guide.understanding.consultation_contracts import (
    ConsultationObservation,
    ProvisionalConsultationConclusion,
)
from app.guide.understanding.consultation_escalation import (
    ConsultationEscalationTrigger,
)
from app.guide.understanding.consultation_questions import (
    ConsultationQuestion,
)
from app.guide.understanding.semantic_contracts import ClarificationCode


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class StartData(_Strict):
    session_id: str


class StageData(_Strict):
    stage: Literal[
        "understanding",
        "retrieval",
        "decision",
        "state",
        "image_observation",
    ]
    summary: str


class IntentData(_Strict):
    mode: PublicIntentMode | Literal[
        "consultation_entry",
        "consultation_answer",
        "consultation_clarification",
        "consultation_provisional",
        "consultation_confirmation",
        "consultation_rejection",
        "consultation_medical_escalation",
        "image_suitability",
    ]
    category_profile: CategoryProfile | None = None


class ClarifyData(_Strict):
    question: str
    clarification_code: ClarificationCode
    intended_responsibility: Literal["recommendation"] | None = None
    intended_recommendation_mode: Literal["fit"] | None = None
    clarification_basis: Literal[
        "fit_selection_evidence_gap"
    ] | None = None
    fit_gap_stage: Literal[
        "decision_selection",
        "public_fact_projection",
    ] | None = None
    fit_decision_status: Literal[
        "SELECTED",
        "TIED_BY_BUSINESS_EVIDENCE",
        "INSUFFICIENT_FOR_WINNER",
        "NO_CANDIDATE",
    ] | None = None
    fit_candidate_count: int | None = Field(default=None, ge=0)
    fit_evidence_ref_count: int | None = Field(default=None, ge=0)
    fit_public_fact_count: int | None = Field(default=None, ge=0)
    pending_turn: PendingTurn | None = Field(
        default=None,
        exclude=True,
    )

    @field_validator("question")
    @classmethod
    def validate_question(cls, value: str) -> str:
        return validate_public_text(value)

    @model_validator(mode="after")
    def validate_fit_selection_proof(self) -> Self:
        proof = (
            self.intended_responsibility,
            self.intended_recommendation_mode,
            self.clarification_basis,
            self.fit_gap_stage,
            self.fit_decision_status,
            self.fit_candidate_count,
            self.fit_evidence_ref_count,
            self.fit_public_fact_count,
        )
        if any(value is not None for value in proof) and not all(
            value is not None for value in proof
        ):
            raise ValueError(
                "fit clarification proof must be complete"
            )
        if self.fit_gap_stage == "decision_selection" and (
            self.fit_decision_status == "SELECTED"
        ):
            raise ValueError(
                "decision selection gap forbids selected winner"
            )
        if self.fit_gap_stage == "public_fact_projection" and (
            self.fit_decision_status != "SELECTED"
            or self.fit_public_fact_count != 0
        ):
            raise ValueError(
                "public fact gap requires selected winner without facts"
            )
        return self


class ImageComparisonReferenceData(_Strict):
    ordinal: int = Field(ge=1, le=4)
    image_id: str
    product_id: int = Field(ge=1)


class ImageComparisonPriceFactData(_Strict):
    reference: ImageComparisonReferenceData
    state: Literal["known", "unknown", "conflict", "not_applicable"]
    value: Decimal | None
    source_refs: list[str]


class ImageComparisonData(_Strict):
    context_source: Literal["current_upload", "confirmed_session"]
    status: Literal["winner", "tie", "insufficient_evidence"]
    references: list[ImageComparisonReferenceData] = Field(
        min_length=2,
        max_length=4,
    )
    winner_reference: ImageComparisonReferenceData | None = None
    tie_reason: Literal[
        "equal_price",
        "equal_lowest_price",
    ] | None = None
    comparison_dimensions: list[Literal["price"]]
    evidence_refs: list[str]
    evaluated_price_facts: list[ImageComparisonPriceFactData] = Field(
        min_length=2,
        max_length=4,
    )


class ImageSuitabilityReferenceData(_Strict):
    ordinal: Literal[1]
    image_id: str
    product_id: int = Field(ge=1)


class ImageSuitabilityFactData(_Strict):
    state: Literal["known", "unknown", "conflict", "not_applicable"]
    values: list[str] | None
    source_refs: list[str]


class ImageSuitabilityData(_Strict):
    status: Literal[
        "suitable",
        "not_suitable",
        "insufficient_evidence",
    ]
    reason: str
    reference: ImageSuitabilityReferenceData
    context_source: Literal[
        "current_explicit_input",
        "confirmed_session",
        "long_term_profile",
    ]
    skin_target: str
    evaluated_skin_fact: ImageSuitabilityFactData
    evidence_refs: list[str]


class SelectionSlotData(_Strict):
    product_id: int = Field(gt=0)
    field_key: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    requested_value: str = Field(min_length=1, max_length=512)
    matched_value: str | None = Field(
        default=None,
        min_length=1,
        max_length=512,
    )
    match_status: Literal["matched", "unknown", "mismatch"]
    rank_strength: Literal[1, 2] | None = None
    source_refs: list[str]
    attribution: Literal[
        "verified_fact",
        "merchant_claim",
        "consumer_report",
    ] | None = None

    @model_validator(mode="after")
    def validate_match_payload(self) -> Self:
        if self.source_refs != sorted(set(self.source_refs)):
            raise ValueError(
                "selection slot source references must be sorted and unique"
            )
        if self.match_status == "matched":
            if (
                self.matched_value is None
                or self.rank_strength is None
                or not self.source_refs
                or self.attribution is None
            ):
                raise ValueError(
                    "matched selection slot requires evidence"
                )
        elif (
            self.matched_value is not None
            or self.rank_strength is not None
            or self.source_refs
            or self.attribution is not None
        ):
            raise ValueError(
                "unmatched selection slot forbids matched evidence"
            )
        return self


class ConceptSlotData(_Strict):
    product_id: int = Field(gt=0)
    field_key: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    concept_id: str = Field(
        pattern=r"^[a-z][a-z0-9_]{1,63}\.[a-z][a-z0-9_]{1,63}$"
    )
    polarity: Literal["prefer", "avoid"]
    match_status: Literal["matched", "unknown", "mismatch"]
    stance: Literal["supports", "opposes"] | None = None
    rank_strength: Literal[1, 2] | None = None
    source_values: list[str]
    source_refs: list[str]
    attribution: Literal[
        "verified_fact",
        "merchant_claim",
        "consumer_report",
    ] | None = None

    @model_validator(mode="after")
    def validate_concept_evidence(self) -> Self:
        if self.source_values != sorted(
            set(self.source_values),
            key=str.casefold,
        ):
            raise ValueError(
                "concept source values must be sorted and unique"
            )
        if self.source_refs != sorted(set(self.source_refs)):
            raise ValueError(
                "concept source references must be sorted and unique"
            )
        if self.match_status == "unknown":
            if (
                self.stance is not None
                or self.rank_strength is not None
                or self.source_values
                or self.source_refs
                or self.attribution is not None
            ):
                raise ValueError(
                    "unknown concept slot forbids evidence"
                )
        elif (
            self.stance is None
            or self.rank_strength is None
            or not self.source_values
            or not self.source_refs
            or self.attribution is None
        ):
            raise ValueError(
                "matched or mismatch concept slot requires evidence"
            )
        return self


class DecisionProcessData(_Strict):
    ordered_product_ids: list[int]
    winner_status: str
    evidence_refs: list[str]
    selection_slots: list[SelectionSlotData] = Field(
        default_factory=list
    )
    concept_slots: list[ConceptSlotData] = Field(default_factory=list)
    relative_comparisons: list[RelativeComparisonResult] = Field(
        default_factory=list
    )
    comparison_data: ImageComparisonData | None = None
    suitability_data: ImageSuitabilityData | None = None


class ScenarioEvidenceData(_Strict):
    records: list[ScenarioEvidenceRecord] = Field(min_length=1)


class ReviewEvidenceData(_Strict):
    approved_source_count: int = Field(ge=0)
    results: list[ReviewReadResult] = Field(min_length=1)
    summaries: list[ReviewSummaryResult] = Field(default_factory=list)


class MerchantClaimEvidenceData(_Strict):
    claim_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    product_id: int = Field(gt=0)
    field_key: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    normalized_value: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
    )
    display_claim: str = Field(min_length=1, max_length=160)
    claim_scope: Literal["ordinary", "safety_transcript"]
    source_label: Literal["商家宣称"] = "商家宣称"
    verification_status: Literal[
        "未经独立核实"
    ] = "未经独立核实"
    allowed_use: Literal[
        "soft_rank_and_display",
        "display_only",
    ]
    source_locator: str = Field(min_length=1, max_length=512)


class MerchantClaimsData(_Strict):
    claims: list[MerchantClaimEvidenceData] = Field(min_length=1)


class ProductEvidenceData(_Strict):
    packet: EvidencePacket


class GeneralKnowledgeCitationData(_Strict):
    knowledge_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    title: str = Field(min_length=1, max_length=256)
    section_title: str = Field(min_length=1, max_length=256)
    public_excerpt: str | None = Field(
        default=None,
        min_length=1,
        max_length=4000,
    )
    source_path: str = Field(
        min_length=1,
        max_length=512,
        pattern=r"^data/knowledge_docs/[^/]+\.md$",
    )
    review_decision: Literal[
        "general_answer",
        "escalation_only",
        "product_specific_redirect",
    ]

    @model_validator(mode="after")
    def validate_public_excerpt(self) -> Self:
        if self.review_decision == "general_answer":
            if self.public_excerpt is None:
                raise ValueError(
                    "general answer citation requires public excerpt"
                )
            validate_final_public_text(self.public_excerpt)
        elif self.public_excerpt is not None:
            raise ValueError(
                "non-answer citation forbids public excerpt"
            )
        return self


class GeneralKnowledgeData(_Strict):
    query: str = Field(min_length=1, max_length=4000)
    citations: list[GeneralKnowledgeCitationData] = Field(max_length=3)
    educational_only: Literal[True] = True
    medical_escalation: bool


class PitfallsData(_Strict):
    pitfalls: list[TypedPitfall]


class CitationData(_Strict):
    id: str = Field(min_length=1)
    type: Literal["guide"] = "guide"
    title: str = Field(min_length=1)
    snippet: str = Field(min_length=1)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    source_kind: Literal[
        "visual_model",
        "ocr_observation",
        "canonical",
    ]

    @field_validator("title", "snippet")
    @classmethod
    def validate_public_copy(cls, value: str) -> str:
        return validate_public_text(value)


class CitationsData(_Strict):
    citations: list[CitationData] = Field(min_length=1)


class AnswerContractData(_Strict):
    product_count: int
    winner_status: str
    has_unknown_skin: bool


class ProductsData(_Strict):
    cards: list[ProductCard]


class MessageData(_Strict):
    content: str = Field(min_length=1)

    @field_validator("content")
    @classmethod
    def validate_content(cls, value: str) -> str:
        return validate_public_text(value)


class ErrorData(_Strict):
    code: Literal[
        "GUIDE_INTERNAL_ERROR",
        "CONSULTATION_INTERNAL_ERROR",
        "IMAGE_BUNDLE_UNAVAILABLE",
        "IMAGE_SINGLE_REQUIRED",
        "IMAGE_COUNT_UNSUPPORTED",
        "IMAGE_RETRIEVAL_UNAVAILABLE",
        "IMAGE_IDENTITY_UNCONFIRMED",
        "IMAGE_CATEGORY_UNSUPPORTED",
    ]
    message: Literal[
        "推荐暂时不可用，请稍后重试。",
        "轻问诊暂时不可用，请稍后重试。",
        "图片引用不可用，请重新上传。",
        "当前单图识别一次只支持 1 张图片。",
        "当前只支持 1 到 4 张图片的识别、适配或商品比较。",
        "图片检索暂时不可用，请稍后重试。",
        "图片信息还不足以确认具体商品，请换一张更清晰的正面图。",
        "当前图片商品不在已开放的防晒或修护精华范围内。",
    ]

    @model_validator(mode="after")
    def validate_code_message_pair(self) -> Self:
        expected = {
            "GUIDE_INTERNAL_ERROR": "推荐暂时不可用，请稍后重试。",
            "CONSULTATION_INTERNAL_ERROR": (
                "轻问诊暂时不可用，请稍后重试。"
            ),
            "IMAGE_BUNDLE_UNAVAILABLE": "图片引用不可用，请重新上传。",
            "IMAGE_SINGLE_REQUIRED": (
                "当前单图识别一次只支持 1 张图片。"
            ),
            "IMAGE_COUNT_UNSUPPORTED": (
                "当前只支持 1 到 4 张图片的识别、适配或商品比较。"
            ),
            "IMAGE_RETRIEVAL_UNAVAILABLE": (
                "图片检索暂时不可用，请稍后重试。"
            ),
            "IMAGE_IDENTITY_UNCONFIRMED": (
                "图片信息还不足以确认具体商品，请换一张更清晰的正面图。"
            ),
            "IMAGE_CATEGORY_UNSUPPORTED": (
                "当前图片商品不在已开放的防晒或修护精华范围内。"
            ),
        }
        if self.message != expected[self.code]:
            raise ValueError("public error code and message must match")
        return self


class ImageObservationData(_Strict):
    observation: ImageIdentityObservation


class ConsultationObservationData(_Strict):
    conversation_version: int = Field(ge=1)
    observations: list[ConsultationObservation] = Field(max_length=32)
    next_question: ConsultationQuestion | None = None
    reason: Literal[
        "answer_required",
        "confirmation_required",
        "rejected_by_user",
    ] | None = None


class ConsultationProvisionalData(_Strict):
    conversation_version: int = Field(ge=1)
    observations: list[ConsultationObservation] = Field(max_length=32)
    conclusion: ProvisionalConsultationConclusion


class MedicalEscalationData(_Strict):
    conversation_version: int = Field(ge=1)
    observations: list[ConsultationObservation] = Field(max_length=32)
    conclusion: ProvisionalConsultationConclusion
    escalation_triggers: list[ConsultationEscalationTrigger] = Field(
        min_length=1,
        max_length=3,
    )
    stop_skincare_advice: Literal[True] = True


class ProfileConfirmationData(_Strict):
    conversation_version: int = Field(ge=1)
    conclusion: ProvisionalConsultationConclusion
    session_profile: SessionProfile
    profile_persistence: (
        ProfilePersistencePlan | ProfilePersistenceRetry | None
    ) = None


class EmptyData(_Strict):
    pass


class EndData(_Strict):
    conversation_version: int = Field(ge=0)


class StartEvent(_Strict):
    event: Literal["start"] = "start"
    data: StartData


class StageEvent(_Strict):
    event: Literal["stage"] = "stage"
    data: StageData


class IntentEvent(_Strict):
    event: Literal["intent"] = "intent"
    data: IntentData


class ClarifyEvent(_Strict):
    event: Literal["clarify"] = "clarify"
    data: ClarifyData


class DecisionProcessEvent(_Strict):
    event: Literal["decision_process"] = "decision_process"
    data: DecisionProcessData


class ScenarioEvidenceEvent(_Strict):
    event: Literal["scenario_evidence"] = "scenario_evidence"
    data: ScenarioEvidenceData


class ReviewEvidenceEvent(_Strict):
    event: Literal["review_evidence"] = "review_evidence"
    data: ReviewEvidenceData


class MerchantClaimsEvent(_Strict):
    event: Literal["merchant_claims"] = "merchant_claims"
    data: MerchantClaimsData


class ProductEvidenceEvent(_Strict):
    event: Literal["product_evidence"] = "product_evidence"
    data: ProductEvidenceData


class GeneralKnowledgeEvent(_Strict):
    event: Literal["general_knowledge"] = "general_knowledge"
    data: GeneralKnowledgeData


class PitfallsEvent(_Strict):
    event: Literal["pitfalls"] = "pitfalls"
    data: PitfallsData


class CitationsEvent(_Strict):
    event: Literal["citations"] = "citations"
    data: CitationsData


class AnswerContractEvent(_Strict):
    event: Literal["answer_contract"] = "answer_contract"
    data: AnswerContractData


class CardDisplayContractEvent(_Strict):
    event: Literal[
        "card_display_contract"
    ] = "card_display_contract"
    data: CardDisplayContract


class PresentationContractEvent(_Strict):
    event: Literal[
        "presentation_contract"
    ] = "presentation_contract"
    data: PublicPresentationContract


class ProductsEvent(_Strict):
    event: Literal["products"] = "products"
    data: ProductsData


class MessageEvent(_Strict):
    event: Literal["message"] = "message"
    data: MessageData


class ErrorEvent(_Strict):
    event: Literal["error"] = "error"
    data: ErrorData


class ImageObservationEvent(_Strict):
    event: Literal["image_observation"] = "image_observation"
    data: ImageObservationData


class ConsultationObservationEvent(_Strict):
    event: Literal[
        "consultation_observation"
    ] = "consultation_observation"
    data: ConsultationObservationData


class ConsultationProvisionalEvent(_Strict):
    event: Literal[
        "consultation_provisional"
    ] = "consultation_provisional"
    data: ConsultationProvisionalData


class MedicalEscalationEvent(_Strict):
    event: Literal["medical_escalation"] = "medical_escalation"
    data: MedicalEscalationData


class ProfileConfirmationEvent(_Strict):
    event: Literal[
        "profile_confirmation"
    ] = "profile_confirmation"
    data: ProfileConfirmationData


class EndEvent(_Strict):
    event: Literal["end"] = "end"
    data: EndData


SseEvent = Annotated[
    StartEvent
    | StageEvent
    | IntentEvent
    | ClarifyEvent
    | DecisionProcessEvent
    | ScenarioEvidenceEvent
    | ReviewEvidenceEvent
    | MerchantClaimsEvent
    | ProductEvidenceEvent
    | GeneralKnowledgeEvent
    | PitfallsEvent
    | CitationsEvent
    | AnswerContractEvent
    | CardDisplayContractEvent
    | ProductsEvent
    | PresentationContractEvent
    | MessageEvent
    | ErrorEvent
    | ImageObservationEvent
    | ConsultationObservationEvent
    | ConsultationProvisionalEvent
    | MedicalEscalationEvent
    | ProfileConfirmationEvent
    | EndEvent,
    Field(discriminator="event"),
]


_OCR_STATE_PUBLIC = {
    "not_run": "未运行包装文字核对",
    "not_configured": "当前未配置包装文字核对",
    "unavailable": "未提取到有效包装文字",
    "observed": "已完成包装文字核对",
}
_OCR_CONSISTENCY_PUBLIC = {
    "not_checked": "未核对",
    "consistent": "与候选商品一致",
    "conflict": "与候选商品不一致",
    "indeterminate": "暂未完整确认",
}


def image_observation_events(
    observations: tuple[ImageIdentityObservation, ...],
) -> tuple[ImageObservationEvent, ...]:
    return tuple(
        ImageObservationEvent(
            data=ImageObservationData(observation=observation)
        )
        for observation in observations
    )


def image_citations_event(
    *,
    observations: tuple[ImageIdentityObservation, ...],
    product_ids: tuple[int, ...],
) -> CitationsEvent:
    citations: list[CitationData] = []
    for observation in observations:
        confidence = observation.visual_confidence
        citations.append(
            CitationData(
                id=f"visual:{observation.image_id}",
                title="图片匹配依据",
                snippet="图片相似度匹配已完成，结果由本次上传图片生成。",
                confidence=(
                    max(0.0, min(1.0, confidence))
                    if confidence is not None
                    else None
                ),
                source_kind="visual_model",
            )
        )
        citations.append(
            CitationData(
                id=f"ocr:{observation.image_id}",
                title="包装文字核对",
                snippet=(
                    f"{_OCR_STATE_PUBLIC[observation.ocr_state.value]}；"
                    "品牌信息"
                    f"{_OCR_CONSISTENCY_PUBLIC[observation.ocr_brand_consistency.value]}；"
                    "商品名称"
                    f"{_OCR_CONSISTENCY_PUBLIC[observation.ocr_product_name_consistency.value]}。"
                    "包装文字只用于辅助确认，不参与商品排序。"
                ),
                source_kind="ocr_observation",
            )
        )
    for product_id in dict.fromkeys(product_ids):
        citations.append(
            CitationData(
                id=f"product:{product_id}",
                title="商品资料",
                snippet="商品身份和卡片信息以已审核的商品资料为准。",
                source_kind="canonical",
            )
        )
    return CitationsEvent(data=CitationsData(citations=citations))
