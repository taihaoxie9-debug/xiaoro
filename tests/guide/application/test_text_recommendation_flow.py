from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
import ast
import hashlib
import json

import pytest

import app.guide.presentation.sse_events as sse_events
from app.guide.adapters.catalog import CanonicalProductReader
from app.guide.application.contracts import UserTurn
from app.guide.application.text_recommendation_flow import (
    TextRecommendationOrchestrator,
)
from app.guide.feedback.consultation_state import ConsultationSubstate
from app.guide.feedback.contracts import (
    ConversationSnapshot,
    DisplayedCandidateRef,
    RecommendationQueryContext,
)
from app.guide.feedback.focus_state import FocusState
from app.guide.feedback.focus_state import ConfirmedImageProductRef
from app.guide.feedback.ports import ConversationStateConflict
from app.guide.feedback.profile_contracts import ProfileOwnerRef
from app.guide.feedback.profile_policy import (
    ResolvedProfileContext,
    ResolvedProfileValue,
    ResolvedValueProvenance,
)
from app.guide.intent.contracts import (
    ConceptConstraint,
    ExclusionConstraint,
)
from app.guide.intent.unified_turn_router import UnifiedRouteDecision
from app.guide.intent.signal_merger import merge_intent_signals
from app.guide.presentation.sse_events import EndData, EndEvent
from app.guide.retrieval.contracts import RetrievalResult
from app.guide.retrieval.category_fact_contracts import (
    AuthorizedCategoryFact,
    SourceClass,
)
from app.guide.retrieval.category_profiles import CategoryProfile
from app.guide.retrieval.product_evidence_assets import (
    ProductEvidenceAssets,
    ProductEvidenceBlock,
    ProductEvidenceManifest,
    product_evidence_id,
)
from app.guide.retrieval.product_evidence_reader import ProductEvidenceReader
from app.guide.retrieval.product_evidence_retrieval import (
    EvidenceQuery,
    ProductEvidenceRetriever,
)
from app.guide.retrieval.product_name_resolver import (
    ResolvedProductBinding,
)
from app.guide.retrieval.general_knowledge_retrieval import (
    GeneralKnowledgeRetriever,
)
from app.guide.retrieval.selection_fact_contracts import SelectionFact
from app.guide.retrieval.selection_parent_concept_contracts import (
    SelectionConceptProjection,
    candidate_id_for,
)
from app.guide.retrieval.selection_parent_concept_reader import (
    SelectionParentConceptReader,
)
from app.guide.understanding.consultation_contracts import (
    ConsultationObservation,
)
from app.guide.understanding.contracts import (
    BudgetDraft,
    CategoryDraft,
    ConstraintChangeDraft,
    EfficacyDraft,
    EfficacyTarget,
    ExclusionDraft,
    PreferenceDraft,
    ProductMentionDraft,
    ReferenceDraft,
    RelativeDraft,
    SkinDraft,
    SkinTarget,
    SourceSpan,
    StructuredUnderstanding,
    TopicCode,
    UnderstandingGoal,
)
from app.guide.understanding.parallel_understanding import (
    ParallelUnderstanding,
)
from app.guide.understanding.context_resolver import (
    resolve_semantic_context,
)
from app.guide.understanding.exact_parsing import parse_exact_constraints
from app.guide.understanding.semantic_contracts import (
    ClarificationCode,
    ConfirmedProfileField,
    SemanticContext,
    SemanticGoal,
    SemanticIntentProposal,
    SemanticProductMention,
    SemanticReference,
)
from app.guide_runtime.composition import (
    build_category_fact_reader,
    build_general_knowledge_assets,
    build_product_evidence_reader,
    build_review_evidence_reader,
    build_selection_fact_reader,
    build_selection_parent_concept_reader,
    compose_text_recommendation_orchestrator,
)
from tests.guide.semantic_test_port import exact_echo_understanding


class RecordingUnderstandingPort:
    def __init__(self, result: StructuredUnderstanding) -> None:
        self.result = result
        self.calls = 0
        self.contexts: list[SemanticContext] = []

    def understand(
        self,
        message: str,
        *,
        context: SemanticContext,
        semantic_required: bool = True,
    ) -> StructuredUnderstanding:
        del message, semantic_required
        self.calls += 1
        self.contexts.append(context)
        return self.result.model_copy(deep=True)


class SequenceUnderstandingPort:
    def __init__(
        self,
        results: tuple[StructuredUnderstanding, ...],
    ) -> None:
        self._results = iter(results)

    def understand(
        self,
        message: str,
        *,
        context: SemanticContext,
        semantic_required: bool = True,
    ) -> StructuredUnderstanding:
        del message, context, semantic_required
        return next(self._results).model_copy(deep=True)


class SequenceSemanticPort:
    def __init__(
        self,
        proposals: tuple[SemanticIntentProposal, ...],
    ) -> None:
        self._proposals = iter(proposals)

    def propose(
        self,
        message: str,
        context: SemanticContext,
    ) -> SemanticIntentProposal:
        del message, context
        return next(self._proposals).model_copy(deep=True)


class BudgetRevisionProposalPort:
    def __init__(self) -> None:
        self.calls = 0

    def propose(
        self,
        message: str,
        context: SemanticContext,
    ) -> SemanticIntentProposal:
        del context
        self.calls += 1
        is_revision_followup = self.calls > 1
        return SemanticIntentProposal(
            goal=(
                SemanticGoal.FOLLOWUP
                if is_revision_followup
                else SemanticGoal.RECOMMENDATION
            ),
            topic=TopicCode.SUNSCREEN,
            concerns=(),
            observations=(),
            references=(
                (
                    SemanticReference(
                        kind="previous_constraint",
                        raw_text="这个条件",
                        start=message.index("这个条件"),
                        end=(
                            message.index("这个条件")
                            + len("这个条件")
                        ),
                    ),
                )
                if is_revision_followup
                else ()
            ),
            confidence=0.99,
            clarification_hint=None,
        )


class RecordingProfileResolver:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(
        self,
        *,
        session_id: str,
        profile_owner: ProfileOwnerRef,
    ) -> ResolvedProfileContext:
        assert session_id
        assert profile_owner
        self.calls += 1
        return ResolvedProfileContext(
            values=(
                ResolvedProfileValue(
                    field="skin_type",
                    value="dry",
                    source="long_term_profile",
                    provenance=ResolvedValueProvenance(
                        source_turn_id="turn_profile_0000000001",
                        source_kind="confirmed_consultation",
                        profile_version=1,
                    ),
                ),
            )
        )


class ResolverAwareUnderstandingPort(RecordingUnderstandingPort):
    def __init__(
        self,
        result: StructuredUnderstanding,
        resolver: RecordingProfileResolver,
    ) -> None:
        super().__init__(result)
        self._resolver = resolver
        self.resolver_calls_at_understanding: list[int] = []

    def understand(
        self,
        message: str,
        *,
        context: SemanticContext,
        semantic_required: bool = True,
    ) -> StructuredUnderstanding:
        self.resolver_calls_at_understanding.append(
            self._resolver.calls
        )
        return super().understand(
            message,
            context=context,
            semantic_required=semantic_required,
        )


class ThreeBaseFinishFacts:
    def read(
        self,
        *,
        product_id: int,
        profile: CategoryProfile,
    ) -> tuple[AuthorizedCategoryFact, ...]:
        assert profile is CategoryProfile.BASE_MAKEUP
        values = {
            82: ("哑光柔雾肌",),
            109: ("清透服帖",),
        }.get(product_id)
        if values is None:
            return ()
        return (
            AuthorizedCategoryFact(
                category_profile=profile,
                field_key="finish",
                value=values,
                resolved_state="known",
                source_classes=(SourceClass.MERCHANT_PARAMETER,),
                source_refs=(f"urn:test:finish:{product_id}",),
                capabilities=frozenset(
                    {"evidence", "display", "compare", "soft_rank"}
                ),
            ),
        )


class ThreeBaseSelectionFacts:
    def read(
        self,
        *,
        product_id: int,
        profile: CategoryProfile,
    ) -> tuple[SelectionFact, ...]:
        assert profile is CategoryProfile.BASE_MAKEUP
        value = {
            82: "哑光柔雾肌",
            109: "清透服帖",
        }.get(product_id)
        if value is None:
            return ()
        return (
            SelectionFact(
                product_id=product_id,
                category_profile=profile,
                subject_scope="exact_product",
                variant_scope=None,
                field_key="finish",
                normalized_value=value,
                rank_strength=1,
                safety_role="ordinary",
                capabilities={"compare", "soft_rank"},
                source_refs=(f"urn:test:finish:{product_id}",),
                attributions={"merchant_claim"},
            ),
        )


class ImageSimilaritySelectionFacts:
    def read(
        self,
        *,
        product_id: int,
        profile: CategoryProfile,
    ) -> tuple[SelectionFact, ...]:
        assert profile is CategoryProfile.SUNCARE
        if product_id not in {53, 55}:
            return ()
        return (
            SelectionFact(
                product_id=product_id,
                category_profile=profile,
                subject_scope="exact_product",
                variant_scope=None,
                field_key="texture",
                normalized_value="轻薄",
                rank_strength=1,
                safety_role="ordinary",
                capabilities={"compare", "soft_rank"},
                source_refs=(
                    f"urn:test:image-similarity:{product_id}",
                ),
                attributions={"verified_fact"},
            ),
        )


def _subset_reader(
    real_reader: CanonicalProductReader,
    tmp_path: Path,
    product_ids: tuple[int, ...],
) -> CanonicalProductReader:
    products_path = tmp_path / "subset_products.jsonl"
    products_text = "\n".join(
        json.dumps(
            real_reader.get(product_id).model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        for product_id in product_ids
    )
    products_path.write_text(products_text, encoding="utf-8")
    unsigned = {
        "product_count": len(product_ids),
        "product_schema_version": "canonical-decision-product-v1",
        "products_file": products_path.name,
        "products_sha256": hashlib.sha256(
            products_text.encode("utf-8")
        ).hexdigest(),
        "schema_version": "canonical-decision-runtime-v1",
    }
    manifest = {
        **unsigned,
        "manifest_sha256": hashlib.sha256(
            json.dumps(
                unsigned,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest(),
    }
    manifest_path = tmp_path / "subset_manifest.json"
    manifest_path.write_text(
        json.dumps(
            manifest,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    return CanonicalProductReader.from_files(
        manifest_path=manifest_path,
        products_path=products_path,
    )


def _fragrance_understanding() -> StructuredUnderstanding:
    return StructuredUnderstanding(
        goal=UnderstandingGoal.RECOMMENDATION,
        topic=TopicCode.FRAGRANCE,
        observations=[],
        exact_constraints=[CategoryDraft(value=TopicCode.FRAGRANCE)],
        semantic_proposals=[],
        signal_trace=[],
        image_references=[],
        uncertainties=[],
        confidence=1.0,
    )


def _product_goal_understanding(
    message: str,
    *,
    goal: UnderstandingGoal,
    topic: TopicCode,
    names: tuple[str, ...],
    question_meaning: str | None = None,
    safety_sensitive: bool = False,
) -> StructuredUnderstanding:
    mentions = []
    for name in names:
        start = message.index(name)
        mentions.append(
            ProductMentionDraft(
                text=name,
                source_span=SourceSpan(
                    start=start,
                    end=start + len(name),
                ),
            )
        )
    return StructuredUnderstanding(
        goal=goal,
        topic=topic,
        observations=[],
        exact_constraints=[CategoryDraft(value=topic)],
        semantic_proposals=[],
        signal_trace=[],
        product_mentions=mentions,
        image_references=[],
        uncertainties=[],
        confidence=0.95,
        question_meaning=question_meaning,
        safety_sensitive=safety_sensitive,
    )


def _flow_evidence_retriever(
    *,
    extra_product_ids: tuple[int, ...] = (),
) -> ProductEvidenceRetriever:
    source_sha = "1" * 64
    image_sha = "2" * 64
    blocks = []
    for index, label, exact_text, meaning, descriptors in (
        (
            0,
            "consumer_self_report",
            (
                "100%消费者认同膜布轻薄服帖；"
                "100%消费者认同膜布不易滑落"
            ),
            "35名敏感肌消费者自评认为膜布服帖且不易滑落。",
            ["服帖", "不易滑落"],
        ),
        (
            1,
            "merchant_cited_test",
            "91%消费者认同水润舒缓，88%消费者认同缓解刺痛",
            "35名敏感肌消费者自评水润舒缓和缓解刺痛。",
            ["35名", "消费者自评", "刺痛"],
        ),
        (
            2,
            "safety_transcript",
            "适合敏感肌及特殊美容项目后使用",
            "商家宣称适合敏感肌和特殊美容项目后使用。",
            ["敏感肌", "特殊美容项目后"],
        ),
    ):
        forbidden = ["hard_filter", "safety_guarantee"]
        if label == "consumer_self_report":
            forbidden.append("clinical_effectiveness")
        payload = {
            "product_id": 78,
            "subject_scope": "exact_product",
            "variant_scope": None,
            "management_label": label,
            "transcription_basis": "visual_transcription",
            "exact_text": exact_text,
            "plain_meaning": meaning,
            "relations": [],
            "qualifiers": {
                "sample_size": 35 if index in {0, 1} else None,
                "population": (
                    "中国敏感肌消费者"
                    if index in {0, 1}
                    else None
                ),
                "method": (
                    "消费者自评" if index in {0, 1} else None
                ),
                "baseline": None,
                "duration": None,
                "disclaimer": (
                    "实际结果因人而异"
                    if index in {0, 1}
                    else None
                ),
                "footnotes": [],
            },
            "free_descriptors": descriptors,
            "review_status": "accepted",
            "allowed_uses": ["answer", "display"],
            "forbidden_uses": forbidden,
            "review_rationale": "文字主链商品证据测试。",
            "selection_review": {
                "decision": "answer_only",
                "visual_confirmed": True,
                "rationale": "该夹具只验证回答检索，不授权选择用途。",
                "projections": [],
            },
            "source": {
                "source_file": "detail_78_ocr.json",
                "source_sha256": source_sha,
                "image_file": f"{index:03d}.jpg",
                "image_index": index,
                "image_sha256": image_sha,
                "source_locator": (
                    "urn:xiaoro:product-detail-image:pid:78:"
                    f"source-sha256:{source_sha}:"
                    f"image-sha256:{image_sha}"
                ),
                "source_url": f"https://example.com/{index}.jpg",
                "recovery_status": "source_record",
                "resolved_image_file": f"{index:03d}.jpg",
                "image_region": [0, 0, 790, 1000],
            },
            "supporting_sources": [],
        }
        blocks.append(
            ProductEvidenceBlock.model_validate(
                {
                    "evidence_id": product_evidence_id(payload),
                    **payload,
                },
                strict=True,
            )
        )
    for product_id in extra_product_ids:
        if product_id == 78:
            continue
        payload = {
            "product_id": product_id,
            "subject_scope": "exact_product",
            "variant_scope": None,
            "management_label": "merchant_cited_test",
            "transcription_basis": "visual_transcription",
            "exact_text": "商家展示了清爽香气和消费者测试证据",
            "plain_meaning": "该商品有清爽香气相关的测试证据。",
            "relations": [],
            "qualifiers": {
                "sample_size": None,
                "population": None,
                "method": "商家引用测试",
                "baseline": None,
                "duration": None,
                "disclaimer": "实际体验因人而异",
                "footnotes": [],
            },
            "free_descriptors": ["清爽香气", "消费者测试证据"],
            "review_status": "accepted",
            "allowed_uses": ["answer", "display"],
            "forbidden_uses": ["hard_filter", "safety_guarantee"],
            "review_rationale": "决策后商品证据绑定测试。",
            "selection_review": {
                "decision": "answer_only",
                "visual_confirmed": True,
                "rationale": "该夹具只验证回答检索，不授权选择用途。",
                "projections": [],
            },
            "source": {
                "source_file": f"detail_{product_id}_ocr.json",
                "source_sha256": source_sha,
                "image_file": f"{product_id:03d}.jpg",
                "image_index": 0,
                "image_sha256": image_sha,
                "source_locator": (
                    "urn:xiaoro:product-detail-image:"
                    f"pid:{product_id}:source-sha256:{source_sha}:"
                    f"image-sha256:{image_sha}"
                ),
                "source_url": (
                    f"https://example.com/{product_id}.jpg"
                ),
                "recovery_status": "source_record",
                "resolved_image_file": f"{product_id:03d}.jpg",
                "image_region": [0, 0, 790, 1000],
            },
            "supporting_sources": [],
        }
        blocks.append(
            ProductEvidenceBlock.model_validate(
                {
                    "evidence_id": product_evidence_id(payload),
                    **payload,
                },
                strict=True,
            )
        )
    ordered = tuple(sorted(blocks, key=lambda item: item.evidence_id))
    product_count = len(
        {block.product_id for block in ordered}
    )
    manifest = ProductEvidenceManifest.model_construct(
        schema_version="product-evidence-v1",
        asset_id="guide-product-evidence-v1",
        asset_version="test",
        evidence_file="test.jsonl",
        evidence_sha256="3" * 64,
        audit_file="audit.jsonl",
        audit_sha256="4" * 64,
        evidence_count=len(ordered),
        product_count=product_count,
        image_count=len(ordered),
        status_counts={"accepted": len(ordered)},
        allowed_use_counts={
            "answer": len(ordered),
            "display": len(ordered),
        },
        manifest_sha256="5" * 64,
    )
    return ProductEvidenceRetriever(
        ProductEvidenceReader(
            ProductEvidenceAssets.model_construct(
                manifest=manifest,
                evidence=ordered,
                audit=(),
            )
        )
    )


def _flow_general_knowledge_retriever() -> GeneralKnowledgeRetriever:
    return GeneralKnowledgeRetriever(
        build_general_knowledge_assets().blocks
    )


def test_direct_named_comparison_resolves_catalog_and_emits_cards(
    real_reader,
    real_product_assets,
    conversation_state,
) -> None:
    names = (
        "安热沙智感倍护防晒乳液GB",
        "理肤泉特护清盈防晒乳 SPF50 PA++++",
    )
    message = f"对比{names[0]}和{names[1]}"
    understanding = RecordingUnderstandingPort(
        _product_goal_understanding(
            message,
            goal=UnderstandingGoal.COMPARISON,
            topic=TopicCode.SUNSCREEN,
            names=names,
        )
    )
    orchestrator = compose_text_recommendation_orchestrator(
        real_reader,
        product_assets=real_product_assets,
        conversation_state=conversation_state,
        understanding=understanding,
    )

    events = list(orchestrator.stream(_turn(message)))

    assert not any(event.event in {"clarify", "error"} for event in events)
    intent = next(event for event in events if event.event == "intent")
    assert intent.data.mode == "comparison"
    products = next(event for event in events if event.event == "products")
    assert set(card.product_id for card in products.data.cards) == {51, 53}
    display = next(
        event
        for event in events
        if event.event == "card_display_contract"
    )
    assert display.data.mode == "comparison"
    assert display.data.max_cards == 2


def test_direct_named_comparison_ignores_efficacy_inside_product_names(
    real_reader,
    real_product_assets,
    conversation_state,
) -> None:
    names = (
        "可复美重组胶原蛋白敷料2盒10贴面部项目创面愈合痤疮皮炎",
        (
            "薇诺娜（WINONA）特护面膜舒敏保湿丝滑面贴膜"
            "6片舒缓修护补水保湿"
        ),
    )
    message = f"对比{names[0]}和{names[1]}"
    exact_constraints, exact_issues = parse_exact_constraints(message)
    semantic_mentions = tuple(
        SemanticProductMention(
            text=name,
            start=message.index(name),
            end=message.index(name) + len(name),
        )
        for name in names
    )
    understanding = RecordingUnderstandingPort(
        merge_intent_signals(
            message=message,
            exact_constraints=exact_constraints,
            exact_issues=exact_issues,
            semantic=SemanticIntentProposal(
                goal=SemanticGoal.COMPARISON,
                topic=TopicCode.SKINCARE,
                concerns=(),
                observations=(),
                references=(),
                product_mentions=semantic_mentions,
                confidence=0.99,
                clarification_hint=None,
                question_meaning="比较两款面膜",
                safety_sensitive=False,
            ),
        )
    )
    orchestrator = compose_text_recommendation_orchestrator(
        real_reader,
        product_assets=real_product_assets,
        conversation_state=conversation_state,
        understanding=understanding,
    )

    events = list(orchestrator.stream(_turn(message)))

    assert not any(
        event.event in {"clarify", "error"} for event in events
    )
    products = next(
        event for event in events if event.event == "products"
    )
    assert {
        card.product_id for card in products.data.cards
    } == {74, 78}


def test_direct_named_suitability_resolves_one_catalog_product(
    real_reader,
    real_product_assets,
    conversation_state,
) -> None:
    name = "理肤泉特护清盈防晒乳 SPF50 PA++++"
    message = f"{name}适合我吗"
    understanding = RecordingUnderstandingPort(
        _product_goal_understanding(
            message,
            goal=UnderstandingGoal.SUITABILITY,
            topic=TopicCode.SUNSCREEN,
            names=(name,),
        )
    )
    orchestrator = compose_text_recommendation_orchestrator(
        real_reader,
        product_assets=real_product_assets,
        conversation_state=conversation_state,
        understanding=understanding,
    )

    events = list(orchestrator.stream(_turn(message)))

    assert not any(event.event in {"clarify", "error"} for event in events)
    intent = next(event for event in events if event.event == "intent")
    assert intent.data.mode == "suitability"
    products = next(event for event in events if event.event == "products")
    assert [card.product_id for card in products.data.cards] == [53]
    display = next(
        event
        for event in events
        if event.event == "card_display_contract"
    )
    assert display.data.mode == "single"
    assert display.data.max_cards == 1


def test_direct_named_suitability_keeps_product_when_name_looks_like_efficacy(
    real_reader,
    real_product_assets,
    conversation_state,
) -> None:
    name = "兰蔻肌底焕活修护精华液 50ml"
    message = f"{name}适合我吗"
    exact_constraints, exact_issues = parse_exact_constraints(message)
    understanding = merge_intent_signals(
        message=message,
        exact_constraints=exact_constraints,
        exact_issues=exact_issues,
        semantic=SemanticIntentProposal(
            goal=SemanticGoal.SUITABILITY,
            topic=TopicCode.SERUM,
            concerns=(),
            observations=(),
            references=(),
            product_mentions=(
                SemanticProductMention(
                    text=name,
                    start=0,
                    end=14,
                ),
            ),
            confidence=0.9,
            clarification_hint=None,
        ),
    )
    orchestrator = compose_text_recommendation_orchestrator(
        real_reader,
        product_assets=real_product_assets,
        conversation_state=conversation_state,
        understanding=RecordingUnderstandingPort(understanding),
    )

    events = list(orchestrator.stream(_turn(message)))

    assert not any(event.event in {"clarify", "error"} for event in events)
    products = next(event for event in events if event.event == "products")
    assert [card.product_id for card in products.data.cards] == [129]
    assert events[-1].event == "end"


def test_knowledge_goal_emits_typed_answer_without_false_clarification(
    real_reader,
    real_product_assets,
    conversation_state,
) -> None:
    understanding = RecordingUnderstandingPort(
        StructuredUnderstanding(
            goal=UnderstandingGoal.KNOWLEDGE,
            topic=TopicCode.SUNSCREEN,
            observations=[],
            exact_constraints=[
                CategoryDraft(value=TopicCode.SUNSCREEN),
            ],
            semantic_proposals=[],
            signal_trace=[],
            image_references=[],
            uncertainties=[],
            confidence=0.95,
        )
    )
    orchestrator = compose_text_recommendation_orchestrator(
        real_reader,
        product_assets=real_product_assets,
        conversation_state=conversation_state,
        understanding=understanding,
    )

    events = list(orchestrator.stream(_turn("防晒为什么需要补涂")))

    assert not any(event.event in {"clarify", "error"} for event in events)
    intent = next(event for event in events if event.event == "intent")
    assert intent.data.mode == "knowledge"
    message = next(event for event in events if event.event == "message")
    assert message.data.content
    assert events[-1].event == "end"


def test_general_knowledge_goal_emits_citations_and_persists_focus(
    real_reader,
    real_product_assets,
    conversation_state,
) -> None:
    understanding = RecordingUnderstandingPort(
        StructuredUnderstanding(
            goal=UnderstandingGoal.KNOWLEDGE,
            topic=TopicCode.SUNSCREEN,
            observations=[],
            exact_constraints=[
                CategoryDraft(value=TopicCode.SUNSCREEN),
            ],
            semantic_proposals=[],
            signal_trace=[],
            image_references=[],
            uncertainties=[],
            confidence=0.95,
            question_meaning="询问SPF和PA防晒指标的含义",
        )
    )
    orchestrator = compose_text_recommendation_orchestrator(
        real_reader,
        product_assets=real_product_assets,
        conversation_state=conversation_state,
        understanding=understanding,
        general_knowledge=_flow_general_knowledge_retriever(),
    )

    events = list(orchestrator.stream(_turn("SPF和PA分别是什么意思")))

    assert not any(
        event.event in {"clarify", "error", "product_evidence"}
        for event in events
    )
    knowledge = next(
        event for event in events if event.event == "general_knowledge"
    )
    assert knowledge.data.educational_only is True
    assert knowledge.data.citations
    answer = next(event for event in events if event.event == "message")
    assert "通用教育资料" in answer.data.content
    assert events[-1].data.conversation_version == 1
    stored = conversation_state.load("s-1")
    assert stored is not None
    assert stored.query_context is None
    assert stored.candidates == ()
    assert stored.focused_general_knowledge_ids == tuple(
        sorted(
            citation.knowledge_id
            for citation in knowledge.data.citations
        )
    )
    assert stored.last_general_knowledge_question == (
        "SPF和PA分别是什么意思"
    )


def test_product_knowledge_never_uses_general_knowledge(
    real_reader,
    real_product_assets,
    conversation_state,
) -> None:
    name = (
        "薇诺娜（WINONA）特护面膜舒敏保湿丝滑面贴膜"
        "6片舒缓修护补水保湿"
    )
    message = f"{name}那个布会不会老往下掉？"
    understanding = RecordingUnderstandingPort(
        _product_goal_understanding(
            message,
            goal=UnderstandingGoal.KNOWLEDGE,
            topic=TopicCode.SKINCARE,
            names=(name,),
            question_meaning="询问面膜是否服帖、是否容易滑落",
        )
    )
    orchestrator = compose_text_recommendation_orchestrator(
        real_reader,
        product_assets=real_product_assets,
        conversation_state=conversation_state,
        understanding=understanding,
        product_evidence=_flow_evidence_retriever(),
        general_knowledge=_flow_general_knowledge_retriever(),
    )

    events = list(orchestrator.stream(_turn(message)))

    assert any(event.event == "product_evidence" for event in events)
    assert not any(
        event.event == "general_knowledge" for event in events
    )
    stored = conversation_state.load("s-1")
    assert stored is not None
    assert stored.focused_general_knowledge_ids == ()
    assert stored.last_general_knowledge_question is None


def test_general_knowledge_followup_reuses_bounded_prior_focus(
    real_reader,
    real_product_assets,
    conversation_state,
) -> None:
    reference = ReferenceDraft(
        kind="current_topic",
        source_span=SourceSpan(start=0, end=1),
    )
    understanding = SequenceUnderstandingPort(
        (
            StructuredUnderstanding(
                goal=UnderstandingGoal.KNOWLEDGE,
                topic=TopicCode.SUNSCREEN,
                observations=[],
                exact_constraints=[
                    CategoryDraft(value=TopicCode.SUNSCREEN),
                ],
                semantic_proposals=[],
                signal_trace=[],
                image_references=[],
                uncertainties=[],
                confidence=0.95,
                question_meaning="询问SPF和PA防晒指标的含义",
            ),
            StructuredUnderstanding(
                goal=UnderstandingGoal.FOLLOWUP,
                topic=TopicCode.SUNSCREEN,
                observations=[],
                exact_constraints=[
                    CategoryDraft(value=TopicCode.SUNSCREEN),
                    reference,
                ],
                semantic_proposals=[],
                signal_trace=[],
                references=[reference],
                image_references=[],
                uncertainties=[],
                confidence=0.95,
                question_meaning="追问海边场景如何选择防晒",
            ),
        )
    )
    orchestrator = compose_text_recommendation_orchestrator(
        real_reader,
        product_assets=real_product_assets,
        conversation_state=conversation_state,
        understanding=understanding,
        general_knowledge=_flow_general_knowledge_retriever(),
    )

    first = list(orchestrator.stream(_turn("SPF和PA分别是什么意思")))
    first_knowledge = next(
        event for event in first if event.event == "general_knowledge"
    )
    second = list(
        orchestrator.stream(
            _turn("那海边场景呢", conversation_version=1)
        )
    )
    second_knowledge = next(
        event for event in second if event.event == "general_knowledge"
    )

    assert first_knowledge.data.citations[0].knowledge_id == (
        second_knowledge.data.citations[0].knowledge_id
    )
    assert second[-1].data.conversation_version == 2


def test_fresh_unrelated_knowledge_clears_prior_and_returns_gap(
    real_reader,
    real_product_assets,
    conversation_state,
) -> None:
    understanding = SequenceUnderstandingPort(
        (
            StructuredUnderstanding(
                goal=UnderstandingGoal.KNOWLEDGE,
                topic=TopicCode.SUNSCREEN,
                observations=[],
                exact_constraints=[
                    CategoryDraft(value=TopicCode.SUNSCREEN),
                ],
                semantic_proposals=[],
                signal_trace=[],
                image_references=[],
                uncertainties=[],
                confidence=0.95,
                question_meaning="询问SPF和PA防晒指标的含义",
            ),
            StructuredUnderstanding(
                goal=UnderstandingGoal.KNOWLEDGE,
                topic=None,
                observations=[],
                exact_constraints=[],
                semantic_proposals=[],
                signal_trace=[],
                image_references=[],
                uncertainties=[],
                confidence=0.95,
                question_meaning="询问上海明日天气",
            ),
        )
    )
    orchestrator = compose_text_recommendation_orchestrator(
        real_reader,
        product_assets=real_product_assets,
        conversation_state=conversation_state,
        understanding=understanding,
        general_knowledge=_flow_general_knowledge_retriever(),
    )

    first = list(orchestrator.stream(_turn("SPF和PA分别是什么意思")))
    assert first[-1].data.conversation_version == 1
    second = list(
        orchestrator.stream(
            _turn("明天上海天气怎么样", conversation_version=1)
        )
    )

    knowledge = next(
        event for event in second if event.event == "general_knowledge"
    )
    assert knowledge.data.citations == []
    answer = next(event for event in second if event.event == "message")
    assert "没有足够相关证据" in answer.data.content
    stored = conversation_state.load("s-1")
    assert stored is not None
    assert stored.focused_general_knowledge_ids == ()
    assert stored.last_general_knowledge_question == (
        "明天上海天气怎么样"
    )


def test_general_knowledge_medical_block_only_escalates(
    real_reader,
    real_product_assets,
    conversation_state,
) -> None:
    understanding = RecordingUnderstandingPort(
        StructuredUnderstanding(
            goal=UnderstandingGoal.KNOWLEDGE,
            topic=TopicCode.SKINCARE,
            observations=[],
            exact_constraints=[
                CategoryDraft(value=TopicCode.SKINCARE),
            ],
            semantic_proposals=[],
            signal_trace=[],
            image_references=[],
            uncertainties=[],
            confidence=0.95,
            question_meaning="询问孕期使用A醇的安全边界",
            safety_sensitive=True,
        )
    )
    orchestrator = compose_text_recommendation_orchestrator(
        real_reader,
        product_assets=real_product_assets,
        conversation_state=conversation_state,
        understanding=understanding,
        general_knowledge=_flow_general_knowledge_retriever(),
    )

    events = list(orchestrator.stream(_turn("孕期可以用A醇吗")))

    knowledge = next(
        event for event in events if event.event == "general_knowledge"
    )
    assert knowledge.data.medical_escalation is True
    assert all(
        citation.review_decision == "escalation_only"
        for citation in knowledge.data.citations
    )
    answer = next(event for event in events if event.event == "message")
    assert "不能据此诊断或保证安全" in answer.data.content


def test_general_knowledge_does_not_change_recommendation_state(
    real_reader,
    real_product_assets,
    conversation_state,
) -> None:
    understanding = SequenceUnderstandingPort(
        (
            StructuredUnderstanding(
                goal=UnderstandingGoal.RECOMMENDATION,
                topic=TopicCode.SUNSCREEN,
                observations=[],
                exact_constraints=[
                    CategoryDraft(value=TopicCode.SUNSCREEN),
                ],
                semantic_proposals=[],
                signal_trace=[],
                image_references=[],
                uncertainties=[],
                confidence=0.95,
            ),
            StructuredUnderstanding(
                goal=UnderstandingGoal.KNOWLEDGE,
                topic=TopicCode.SUNSCREEN,
                observations=[],
                exact_constraints=[
                    CategoryDraft(value=TopicCode.SUNSCREEN),
                ],
                semantic_proposals=[],
                signal_trace=[],
                image_references=[],
                uncertainties=[],
                confidence=0.95,
                question_meaning="询问SPF和PA防晒指标的含义",
            ),
        )
    )
    orchestrator = compose_text_recommendation_orchestrator(
        real_reader,
        product_assets=real_product_assets,
        conversation_state=conversation_state,
        understanding=understanding,
        general_knowledge=_flow_general_knowledge_retriever(),
    )

    first = list(orchestrator.stream(_turn("推荐防晒")))
    assert first[-1].data.conversation_version == 1
    before = conversation_state.load("s-1")
    assert before is not None
    second = list(
        orchestrator.stream(
            _turn("SPF和PA分别是什么意思", conversation_version=1)
        )
    )
    assert second[-1].data.conversation_version == 2
    after = conversation_state.load("s-1")

    assert after is not None
    assert after.query_context == before.query_context
    assert after.candidates == before.candidates
    assert (
        after.focused_candidate_ordinal
        == before.focused_candidate_ordinal
    )
    assert after.focused_general_knowledge_ids
    assert after.last_general_knowledge_question == (
        "SPF和PA分别是什么意思"
    )


def test_named_knowledge_recovers_canonical_mention_omitted_by_model(
    real_reader,
    real_product_assets,
    conversation_state,
) -> None:
    name = "蓝胖子防晒霜50ml"
    message = f"{name}包装上到底写没写防水？"
    understanding = RecordingUnderstandingPort(
        StructuredUnderstanding(
            goal=UnderstandingGoal.KNOWLEDGE,
            topic=TopicCode.SUNSCREEN,
            observations=[],
            exact_constraints=[
                CategoryDraft(value=TopicCode.SUNSCREEN),
            ],
            semantic_proposals=[],
            signal_trace=[],
            image_references=[],
            uncertainties=[],
            confidence=0.95,
            question_meaning="询问防水等级和包装标识",
        )
    )
    orchestrator = compose_text_recommendation_orchestrator(
        real_reader,
        product_assets=real_product_assets,
        conversation_state=conversation_state,
        understanding=understanding,
        product_evidence=_flow_evidence_retriever(
            extra_product_ids=(56,),
        ),
    )

    events = list(orchestrator.stream(_turn(message)))

    assert not any(event.event in {"clarify", "error"} for event in events)
    evidence = next(
        event for event in events if event.event == "product_evidence"
    )
    assert evidence.data.packet.query.product_ids == (56,)
    assert evidence.data.packet.query.product_identity_names == (name,)
    assert evidence.data.packet.query.product_mention_spans == (
        (0, len(name)),
    )


def test_product_question_retrieves_grounded_evidence_without_fixed_tag(
    real_reader,
    real_product_assets,
    conversation_state,
) -> None:
    name = (
        "薇诺娜（WINONA）特护面膜舒敏保湿丝滑面贴膜"
        "6片舒缓修护补水保湿"
    )
    message = f"{name}那个布会不会老往下掉？"
    understanding = RecordingUnderstandingPort(
        _product_goal_understanding(
            message,
            goal=UnderstandingGoal.KNOWLEDGE,
            topic=TopicCode.SKINCARE,
            names=(name,),
            question_meaning="询问面膜是否服帖、是否容易滑落",
        )
    )
    orchestrator = compose_text_recommendation_orchestrator(
        real_reader,
        product_assets=real_product_assets,
        conversation_state=conversation_state,
        understanding=understanding,
        product_evidence=_flow_evidence_retriever(),
    )

    events = list(orchestrator.stream(_turn(message)))

    assert not any(event.event in {"clarify", "error"} for event in events)
    evidence = next(
        event for event in events if event.event == "product_evidence"
    )
    assert evidence.data.packet.selected[0].evidence.product_id == 78
    assert "不易滑落" in (
        evidence.data.packet.selected[0].evidence.exact_text
    )
    answer = next(event for event in events if event.event == "message")
    assert "消费者自评" in answer.data.content
    assert "不易滑落" in answer.data.content


def test_current_item_reference_uses_focus_state_product() -> None:
    snapshot = ConversationSnapshot(
        session_id="focus-current-item",
        version=1,
        query_context=RecommendationQueryContext(
            category="serum",
        ),
        candidates=(
            DisplayedCandidateRef(
                product_id=38,
                ordinal=1,
                skin_match="unknown",
                matched_efficacies=(),
            ),
            DisplayedCandidateRef(
                product_id=91,
                ordinal=2,
                skin_match="unknown",
                matched_efficacies=(),
            ),
        ),
        focus_state=FocusState(
            active_processor="product_knowledge",
            current_product_id=91,
        ),
    )

    resolution = TextRecommendationOrchestrator._resolve_reference_products(
        (
            ReferenceDraft(
                kind="current_item",
                source_span=SourceSpan(start=0, end=4),
            ),
        ),
        snapshot=snapshot,
    )

    assert resolution.issue is None
    assert [item.product_id for item in resolution.bindings] == [91]


def test_failed_product_surface_falls_back_to_typed_current_reference(
    real_reader,
    real_product_assets,
    conversation_state,
) -> None:
    message = "回到玉泽那支，继续查它的资料"
    understanding = _product_goal_understanding(
        message,
        goal=UnderstandingGoal.FOLLOWUP,
        topic=TopicCode.SERUM,
        names=("玉泽那支",),
        question_meaning="继续查询当前商品资料",
    ).model_copy(
        update={
            "references": [
                ReferenceDraft(
                    kind="current_item",
                    source_span=SourceSpan(start=2, end=6),
                )
            ]
        },
        deep=True,
    )
    snapshot = ConversationSnapshot(
        session_id="fallback-current-item",
        version=2,
        query_context=RecommendationQueryContext(
            category="serum",
        ),
        candidates=(
            DisplayedCandidateRef(
                product_id=38,
                ordinal=1,
                skin_match="unknown",
                matched_efficacies=(),
            ),
            DisplayedCandidateRef(
                product_id=91,
                ordinal=2,
                skin_match="unknown",
                matched_efficacies=(),
            ),
        ),
        focused_candidate_ordinal=2,
        focus_state=FocusState(
            active_processor="general_knowledge",
            current_product_id=91,
        ),
    )
    orchestrator = compose_text_recommendation_orchestrator(
        real_reader,
        product_assets=real_product_assets,
        conversation_state=conversation_state,
    )

    resolution = orchestrator.resolve_product_resolution(
        message=message,
        understanding=understanding,
        snapshot=snapshot,
    )

    assert resolution.issue is None
    assert [item.product_id for item in resolution.bindings] == [91]
    assert resolution.bindings[0].source_text == "current_item:2"


def test_duplicate_reference_forms_to_same_product_are_deduplicated() -> None:
    snapshot = ConversationSnapshot(
        session_id="same-product-references",
        version=1,
        query_context=RecommendationQueryContext(category="sunscreen"),
        candidates=(
            DisplayedCandidateRef(
                product_id=56,
                ordinal=1,
                skin_match="not_applicable",
                matched_efficacies=(),
            ),
            DisplayedCandidateRef(
                product_id=51,
                ordinal=2,
                skin_match="not_applicable",
                matched_efficacies=(),
            ),
        ),
        focused_candidate_ordinal=2,
        focus_state=FocusState(
            active_processor="general_knowledge",
            current_product_id=51,
        ),
    )

    resolution = TextRecommendationOrchestrator._resolve_reference_products(
        (
            ReferenceDraft(kind="current_item"),
            ReferenceDraft(kind="candidate_ordinal", ordinal=2),
        ),
        snapshot=snapshot,
    )

    assert resolution.issue is None
    assert [item.product_id for item in resolution.bindings] == [51]


def test_specific_ordinal_inside_batch_overrides_batch_resolution() -> None:
    snapshot = ConversationSnapshot(
        session_id="specific-reference-over-batch",
        version=1,
        query_context=RecommendationQueryContext(category="sunscreen"),
        candidates=(
            DisplayedCandidateRef(
                product_id=56,
                ordinal=1,
                skin_match="not_applicable",
                matched_efficacies=(),
            ),
            DisplayedCandidateRef(
                product_id=51,
                ordinal=2,
                skin_match="not_applicable",
                matched_efficacies=(),
            ),
        ),
    )

    resolution = TextRecommendationOrchestrator._resolve_reference_products(
        (
            ReferenceDraft(kind="current_batch"),
            ReferenceDraft(kind="candidate_ordinal", ordinal=2),
        ),
        snapshot=snapshot,
    )

    assert resolution.issue is None
    assert [item.product_id for item in resolution.bindings] == [51]
    assert resolution.bindings[0].source_text == "candidate_ordinal:2"


def test_reference_forms_to_different_products_remain_distinct() -> None:
    snapshot = ConversationSnapshot(
        session_id="different-product-references",
        version=1,
        query_context=RecommendationQueryContext(category="sunscreen"),
        candidates=(
            DisplayedCandidateRef(
                product_id=56,
                ordinal=1,
                skin_match="not_applicable",
                matched_efficacies=(),
            ),
            DisplayedCandidateRef(
                product_id=51,
                ordinal=2,
                skin_match="not_applicable",
                matched_efficacies=(),
            ),
        ),
        focused_candidate_ordinal=1,
        focus_state=FocusState(
            active_processor="product_knowledge",
            current_product_id=56,
        ),
    )

    resolution = TextRecommendationOrchestrator._resolve_reference_products(
        (
            ReferenceDraft(kind="current_item"),
            ReferenceDraft(kind="candidate_ordinal", ordinal=2),
        ),
        snapshot=snapshot,
    )

    assert resolution.issue is None
    assert [
        item.product_id for item in resolution.bindings
    ] == [56, 51]


def test_product_evidence_followup_uses_current_item_and_question_meaning(
    real_reader,
    real_product_assets,
    conversation_state,
) -> None:
    name = (
        "薇诺娜（WINONA）特护面膜舒敏保湿丝滑面贴膜"
        "6片舒缓修护补水保湿"
    )
    first_message = f"{name}适合我吗"
    current_reference = ReferenceDraft(
        kind="current_item",
        source_span=SourceSpan(start=0, end=1),
    )
    understanding = SequenceUnderstandingPort(
        (
            _product_goal_understanding(
                first_message,
                goal=UnderstandingGoal.SUITABILITY,
                topic=TopicCode.SKINCARE,
                names=(name,),
            ),
            StructuredUnderstanding(
                goal=UnderstandingGoal.FOLLOWUP,
                topic=TopicCode.SKINCARE,
                observations=[],
                exact_constraints=[],
                preference_drafts=[],
                semantic_proposals=[],
                signal_trace=[],
                references=[current_reference],
                product_mentions=[],
                image_references=[],
                uncertainties=[],
                confidence=0.95,
                question_meaning="追问35名消费者测试的类型和可靠性",
                safety_sensitive=False,
            ),
        )
    )
    orchestrator = compose_text_recommendation_orchestrator(
        real_reader,
        product_assets=real_product_assets,
        conversation_state=conversation_state,
        understanding=understanding,
        product_evidence=_flow_evidence_retriever(),
    )

    first = list(orchestrator.stream(_turn(first_message)))
    assert first[-1].event == "end"
    second = list(
        orchestrator.stream(
            _turn(
                "它那个35个人测的靠谱吗？",
                conversation_version=1,
            )
        )
    )

    assert not any(event.event in {"clarify", "error"} for event in second)
    evidence = next(
        event for event in second if event.event == "product_evidence"
    )
    assert evidence.data.packet.query.product_ids == (78,)
    answer = next(event for event in second if event.event == "message")
    assert "35名" in answer.data.content
    assert "消费者自评" in answer.data.content


def test_direct_knowledge_persists_product_and_evidence_for_followup(
    real_reader,
    real_product_assets,
    conversation_state,
) -> None:
    name = (
        "薇诺娜（WINONA）特护面膜舒敏保湿丝滑面贴膜"
        "6片舒缓修护补水保湿"
    )
    first_message = f"{name}那个布会不会老往下掉？"
    current_reference = ReferenceDraft(
        kind="current_item",
        source_span=SourceSpan(start=0, end=1),
    )
    understanding = SequenceUnderstandingPort(
        (
            _product_goal_understanding(
                first_message,
                goal=UnderstandingGoal.KNOWLEDGE,
                topic=TopicCode.SKINCARE,
                names=(name,),
                question_meaning="询问面膜是否服帖、是否容易滑落",
            ),
            StructuredUnderstanding(
                goal=UnderstandingGoal.FOLLOWUP,
                topic=TopicCode.SKINCARE,
                observations=[],
                exact_constraints=[],
                preference_drafts=[],
                semantic_proposals=[],
                signal_trace=[],
                references=[current_reference],
                product_mentions=[],
                image_references=[],
                uncertainties=[],
                confidence=0.95,
                question_meaning="追问35名消费者测试的类型和可靠性",
                safety_sensitive=False,
            ),
        )
    )
    orchestrator = compose_text_recommendation_orchestrator(
        real_reader,
        product_assets=real_product_assets,
        conversation_state=conversation_state,
        understanding=understanding,
        product_evidence=_flow_evidence_retriever(),
    )

    first = list(orchestrator.stream(_turn(first_message)))
    stored = conversation_state.load("s-1")

    assert first[-1].data.conversation_version == 1
    assert stored is not None
    assert [item.product_id for item in stored.candidates] == [78]
    assert stored.focused_candidate_ordinal == 1
    assert stored.focused_evidence_ids

    second = list(
        orchestrator.stream(
            _turn(
                "它那个35个人测的靠谱吗？",
                conversation_version=1,
            )
        )
    )

    assert not any(
        event.event in {"clarify", "error"} for event in second
    )
    evidence = next(
        event for event in second if event.event == "product_evidence"
    )
    assert evidence.data.packet.query.product_ids == (78,)
    assert second[-1].data.conversation_version == 2


def test_model_knowledge_pronoun_replays_as_grounded_followup(
    real_reader,
    real_product_assets,
    conversation_state,
) -> None:
    name = (
        "薇诺娜（WINONA）特护面膜舒敏保湿丝滑面贴膜"
        "6片舒缓修护补水保湿"
    )
    first_message = f"{name}那个布会不会老往下掉？"
    semantic = SequenceSemanticPort(
        (
            SemanticIntentProposal(
                goal=SemanticGoal.KNOWLEDGE,
                topic=TopicCode.SKINCARE,
                concerns=(),
                observations=(),
                references=(),
                product_mentions=(
                    SemanticProductMention(
                        text=name,
                        start=0,
                        end=len(name),
                    ),
                ),
                confidence=0.9,
                clarification_hint=None,
                question_meaning="询问面膜是否服帖、是否容易滑落",
            ),
            SemanticIntentProposal(
                goal=SemanticGoal.KNOWLEDGE,
                topic=TopicCode.SKINCARE,
                concerns=(),
                observations=(),
                references=(),
                product_mentions=(),
                confidence=0.9,
                clarification_hint=None,
                question_meaning="询问35人测试的可靠性",
            ),
        )
    )
    orchestrator = compose_text_recommendation_orchestrator(
        real_reader,
        product_assets=real_product_assets,
        conversation_state=conversation_state,
        understanding=ParallelUnderstanding(semantic=semantic),
        product_evidence=_flow_evidence_retriever(),
    )

    first = list(orchestrator.stream(_turn(first_message)))
    second = list(
        orchestrator.stream(
            _turn(
                "它那个35个人测的靠谱吗？",
                conversation_version=1,
            )
        )
    )

    assert first[-1].data.conversation_version == 1
    assert not any(
        event.event in {"clarify", "error"} for event in second
    )
    intent = next(event for event in second if event.event == "intent")
    assert intent.data.mode == "followup"
    evidence = next(
        event for event in second if event.event == "product_evidence"
    )
    assert evidence.data.packet.query.product_ids == (78,)
    answer = next(event for event in second if event.event == "message")
    assert "35名" in answer.data.content
    assert "消费者自评" in answer.data.content
    presentation = next(
        event
        for event in second
        if event.event == "presentation_contract"
    )
    assert presentation.data.mode == "product_knowledge"
    assert [
        section.kind for section in presentation.data.sections
    ] == ["product", "full_cards"]
    assert second[-1].data.conversation_version == 2


def test_product_safety_question_stays_fail_closed(
    real_reader,
    real_product_assets,
    conversation_state,
) -> None:
    name = (
        "薇诺娜（WINONA）特护面膜舒敏保湿丝滑面贴膜"
        "6片舒缓修护补水保湿"
    )
    message = f"{name}医美后一定安全吗？"
    understanding = RecordingUnderstandingPort(
        _product_goal_understanding(
            message,
            goal=UnderstandingGoal.KNOWLEDGE,
            topic=TopicCode.SKINCARE,
            names=(name,),
            question_meaning="询问特殊美容项目后使用是否安全",
            safety_sensitive=True,
        )
    )
    orchestrator = compose_text_recommendation_orchestrator(
        real_reader,
        product_assets=real_product_assets,
        conversation_state=conversation_state,
        understanding=understanding,
        product_evidence=_flow_evidence_retriever(),
    )

    events = list(orchestrator.stream(_turn(message)))

    assert not any(event.event in {"clarify", "error"} for event in events)
    answer = next(event for event in events if event.event == "message")
    assert "不能作为安全保证或硬筛依据" in answer.data.content
    assert "一定安全" not in answer.data.content


def test_direct_suitability_attaches_evidence_after_decision(
    real_reader,
    real_product_assets,
    conversation_state,
) -> None:
    name = (
        "薇诺娜（WINONA）特护面膜舒敏保湿丝滑面贴膜"
        "6片舒缓修护补水保湿"
    )
    message = f"{name}容易往下掉吗，适合边走边敷吗？"
    understanding = RecordingUnderstandingPort(
        _product_goal_understanding(
            message,
            goal=UnderstandingGoal.SUITABILITY,
            topic=TopicCode.SKINCARE,
            names=(name,),
            question_meaning="询问面膜是否服帖和容易滑落",
        )
    )
    orchestrator = compose_text_recommendation_orchestrator(
        real_reader,
        product_assets=real_product_assets,
        conversation_state=conversation_state,
        understanding=understanding,
        product_evidence=_flow_evidence_retriever(),
    )

    events = list(orchestrator.stream(_turn(message)))

    event_names = [event.event for event in events]
    products = next(
        event for event in events if event.event == "products"
    )
    evidence = next(
        event for event in events if event.event == "product_evidence"
    )
    assert [card.product_id for card in products.data.cards] == [78]
    assert evidence.data.packet.query.product_ids == (78,)
    assert {
        item.evidence.product_id
        for item in evidence.data.packet.selected
    } == {78}
    assert event_names.index("decision_process") < event_names.index(
        "product_evidence"
    )
    assert event_names.index("product_evidence") < event_names.index(
        "message"
    )


def test_direct_comparison_attaches_only_resolved_product_evidence(
    real_reader,
    real_product_assets,
    conversation_state,
) -> None:
    names = (
        "薇诺娜（WINONA）特护面膜舒敏保湿丝滑面贴膜"
        "6片舒缓修护补水保湿",
        "可复美重组胶原蛋白敷料2盒10贴面部项目创面愈合痤疮皮炎",
    )
    message = f"对比{names[0]}和{names[1]}的消费者测试证据"
    understanding = RecordingUnderstandingPort(
        _product_goal_understanding(
            message,
            goal=UnderstandingGoal.COMPARISON,
            topic=TopicCode.SKINCARE,
            names=names,
            question_meaning="比较两款面膜的消费者测试证据",
        )
    )
    orchestrator = compose_text_recommendation_orchestrator(
        real_reader,
        product_assets=real_product_assets,
        conversation_state=conversation_state,
        understanding=understanding,
        product_evidence=_flow_evidence_retriever(
            extra_product_ids=(74, 999),
        ),
    )

    events = list(orchestrator.stream(_turn(message)))

    products = next(
        event for event in events if event.event == "products"
    )
    evidence = next(
        event for event in events if event.event == "product_evidence"
    )
    visible_product_ids = tuple(
        card.product_id for card in products.data.cards
    )
    assert set(visible_product_ids) == {74, 78}
    assert evidence.data.packet.query.product_ids == visible_product_ids
    assert {
        item.evidence.product_id
        for item in evidence.data.packet.selected
    } == {74, 78}
    assert all(
        item.evidence.product_id != 999
        for item in evidence.data.packet.selected
    )


def test_recommendation_attaches_evidence_without_changing_decision(
    real_reader,
    real_product_assets,
) -> None:
    message = "帮我买点闻起来清爽的香水"
    baseline = compose_text_recommendation_orchestrator(
        real_reader,
        product_assets=real_product_assets,
        understanding=RecordingUnderstandingPort(
            _fragrance_understanding()
        ),
    )
    baseline_events = list(baseline.stream(_turn(message)))
    baseline_decision = next(
        event
        for event in baseline_events
        if event.event == "decision_process"
    )
    expected_product_ids = tuple(
        baseline_decision.data.ordered_product_ids
    )
    grounded = compose_text_recommendation_orchestrator(
        real_reader,
        product_assets=real_product_assets,
        understanding=RecordingUnderstandingPort(
            _fragrance_understanding()
        ),
        product_evidence=_flow_evidence_retriever(
            extra_product_ids=(*expected_product_ids, 999),
        ),
    )

    events = list(grounded.stream(_turn(message)))

    event_names = [event.event for event in events]
    decision = next(
        event for event in events if event.event == "decision_process"
    )
    products = next(
        event for event in events if event.event == "products"
    )
    evidence = next(
        event for event in events if event.event == "product_evidence"
    )
    assert tuple(decision.data.ordered_product_ids) == expected_product_ids
    assert tuple(
        card.product_id for card in products.data.cards
    ) == expected_product_ids
    assert evidence.data.packet.query.product_ids == expected_product_ids
    assert {
        item.evidence.product_id
        for item in evidence.data.packet.selected
    } == set(expected_product_ids)
    assert all(
        item.evidence.product_id != 999
        for item in evidence.data.packet.selected
    )
    assert event_names.index("decision_process") < event_names.index(
        "product_evidence"
    )
    assert event_names.index("product_evidence") < event_names.index(
        "message"
    )


def test_comparison_current_batch_resolves_snapshot_candidates(
    real_reader,
    real_product_assets,
    conversation_state,
) -> None:
    comparison_reference = ReferenceDraft(
        kind="current_batch",
        source_span=None,
    )
    understanding = SequenceUnderstandingPort((
        _fragrance_understanding(),
        StructuredUnderstanding(
            goal=UnderstandingGoal.COMPARISON,
            topic=TopicCode.FRAGRANCE,
            observations=[],
            exact_constraints=[
                CategoryDraft(value=TopicCode.FRAGRANCE),
            ],
            semantic_proposals=[],
            preference_drafts=[
                PreferenceDraft(
                    field_key="usage_context",
                    value="日常",
                )
            ],
            signal_trace=[],
            references=[comparison_reference],
            image_references=[],
            uncertainties=[],
            confidence=0.95,
        ),
    ))
    root = Path(__file__).resolve().parents[3]
    category_facts = build_category_fact_reader(
        real_reader,
        repo_root=root,
    )
    product_evidence = build_product_evidence_reader(root)
    orchestrator = compose_text_recommendation_orchestrator(
        real_reader,
        product_assets=real_product_assets,
        conversation_state=conversation_state,
        category_fact_port=category_facts,
        selection_facts=build_selection_fact_reader(
            category_facts=category_facts,
            product_evidence=product_evidence,
        ),
        understanding=understanding,
    )
    first = list(orchestrator.stream(_turn("推荐香水")))
    first_products = next(
        event for event in first if event.event == "products"
    )

    compared = list(
        orchestrator.stream(
            _turn("这几款对比一下", conversation_version=1)
        )
    )

    assert not any(
        event.event in {"clarify", "error"}
        for event in compared
    )
    intent = next(
        event for event in compared if event.event == "intent"
    )
    assert intent.data.mode == "comparison"
    compared_products = next(
        event for event in compared if event.event == "products"
    )
    assert {
        card.product_id for card in compared_products.data.cards
    } == {
        card.product_id for card in first_products.data.cards
    }
    decision = next(
        event for event in compared
        if event.event == "decision_process"
    )
    assert len(decision.data.selection_slots) == len(
        compared_products.data.cards
    )
    assert {
        item.field_key for item in decision.data.selection_slots
    } == {"usage_context"}
    assert {
        item.match_status for item in decision.data.selection_slots
    } <= {"matched", "unknown", "mismatch"}


def test_text_flow_consumes_injected_understanding_once(
    real_reader,
    real_product_assets,
    conversation_state,
) -> None:
    understanding = RecordingUnderstandingPort(_fragrance_understanding())
    orchestrator = compose_text_recommendation_orchestrator(
        real_reader,
        product_assets=real_product_assets,
        conversation_state=conversation_state,
        understanding=understanding,
    )

    events = list(
        orchestrator.stream(_turn("帮我买点闻起来清爽的香水"))
    )

    assert understanding.calls == 1
    intent = next(event for event in events if event.event == "intent")
    assert intent.data.category_profile.value == "fragrance"
    assert isinstance(understanding.contexts[0], SemanticContext)


def test_injected_understanding_receives_typed_context_without_product_facts(
    real_reader,
    real_product_assets,
    conversation_state,
) -> None:
    understanding = RecordingUnderstandingPort(_fragrance_understanding())
    orchestrator = compose_text_recommendation_orchestrator(
        real_reader,
        product_assets=real_product_assets,
        conversation_state=conversation_state,
        understanding=understanding,
    )

    list(orchestrator.stream(_turn("帮我买点香水")))

    context = understanding.contexts[0]
    dumped = context.model_dump_json().casefold()
    assert "product" not in dumped
    assert "\"candidates\"" not in dumped


def test_confirmed_profile_fields_reach_understanding_before_profile_fill(
    real_reader,
    real_product_assets,
    conversation_state,
) -> None:
    resolver = RecordingProfileResolver()
    understanding = RecordingUnderstandingPort(_fragrance_understanding())
    orchestrator = compose_text_recommendation_orchestrator(
        real_reader,
        product_assets=real_product_assets,
        conversation_state=conversation_state,
        understanding=understanding,
        profile_resolver=resolver,
    )

    events = list(
        orchestrator.stream(
            _turn(
                "帮我买点闻起来清爽的香水",
                profile_owner=_profile_owner("profile_context_0001"),
            )
        )
    )

    assert not any(event.event == "error" for event in events)
    assert resolver.calls == 1
    assert understanding.contexts[0].confirmed_profile_fields == (
        ConfirmedProfileField.SKIN_TYPE,
    )
    assert "dry" not in understanding.contexts[0].model_dump_json()


def test_profile_resolver_is_called_once_and_reused_for_profile_fill(
    real_reader,
    real_product_assets,
    conversation_state,
) -> None:
    resolver = RecordingProfileResolver()
    understanding = ResolverAwareUnderstandingPort(
        _fragrance_understanding(),
        resolver,
    )
    orchestrator = compose_text_recommendation_orchestrator(
        real_reader,
        product_assets=real_product_assets,
        conversation_state=conversation_state,
        understanding=understanding,
        profile_resolver=resolver,
    )

    events = list(
        orchestrator.stream(
            _turn(
                "帮我买点闻起来清爽的香水",
                profile_owner=_profile_owner("profile_context_0002"),
            )
        )
    )

    stored = conversation_state.load("s-1")
    assert not any(event.event == "error" for event in events)
    assert understanding.resolver_calls_at_understanding == [1]
    assert resolver.calls == 1
    assert stored is not None
    assert stored.query_context is not None
    assert stored.query_context.skin == "dry"


def test_offline_fixture_uses_injected_semantic_understanding(
    orchestrator,
) -> None:
    events = list(
        orchestrator.stream(_turn("500 内适合油敏肌的防晒"))
    )
    products = next(item for item in events if item.event == "products")
    assert [card.product_id for card in products.data.cards] == [101, 26, 52]


def test_colloquial_finish_facet_ranks_match_unknown_mismatch_without_recall(
    real_reader,
    real_product_assets,
    conversation_state,
    tmp_path: Path,
) -> None:
    subset = _subset_reader(real_reader, tmp_path, (82, 108, 109))
    with_facet = StructuredUnderstanding(
        goal=UnderstandingGoal.RECOMMENDATION,
        topic=TopicCode.BASE_MAKEUP,
        observations=[],
        exact_constraints=[
            CategoryDraft(value=TopicCode.BASE_MAKEUP),
        ],
        preference_drafts=[
            PreferenceDraft(field_key="finish", value="哑光"),
        ],
        semantic_proposals=[],
        signal_trace=[],
        image_references=[],
        uncertainties=[],
        confidence=0.95,
    )
    without_facet = with_facet.model_copy(
        update={"preference_drafts": []},
        deep=True,
    )
    ranked = compose_text_recommendation_orchestrator(
        subset,
        product_assets=real_product_assets,
        conversation_state=conversation_state,
        category_fact_port=ThreeBaseFinishFacts(),
        selection_facts=ThreeBaseSelectionFacts(),
        understanding=RecordingUnderstandingPort(with_facet),
    )
    baseline = compose_text_recommendation_orchestrator(
        subset,
        product_assets=real_product_assets,
        category_fact_port=ThreeBaseFinishFacts(),
        selection_facts=ThreeBaseSelectionFacts(),
        understanding=RecordingUnderstandingPort(without_facet),
    )

    ranked_cards = ranked.orchestrate(
        _turn("想要哑光一点的粉底")
    ).structured_events
    baseline_cards = baseline.orchestrate(
        _turn("推荐粉底")
    ).structured_events

    assert [card.product_id for card in ranked_cards] == [82, 108, 109]
    assert {card.product_id for card in ranked_cards} == {
        card.product_id for card in baseline_cards
    }


def test_concept_rank_reason_uses_same_source_refs_as_decision_event(
    real_reader,
    real_product_assets,
    conversation_state,
    tmp_path: Path,
) -> None:
    subset = _subset_reader(real_reader, tmp_path, (82, 108, 109))
    source_ref = "urn:test:finish:82"
    projection = SelectionConceptProjection.model_validate(
        {
            "candidate_id": candidate_id_for(
                profile="base_makeup",
                field_key="finish",
                normalized_value="哑光柔雾肌",
                product_ids=(82, 109),
                rank_strengths=(1,),
                source_refs=(source_ref,),
            ),
            "profile": "base_makeup",
            "field_key": "finish",
            "normalized_value": "哑光柔雾肌",
            "product_ids": [82, 109],
            "rank_strengths": [1],
            "source_refs": [source_ref],
            "concept_id": "finish.matte",
            "stance": "supports",
            "comparability": "binary",
            "order_value": None,
            "rationale": "测试审核过的哑光父概念排序理由。",
        },
        strict=True,
    )
    understanding = StructuredUnderstanding(
        goal=UnderstandingGoal.RECOMMENDATION,
        topic=TopicCode.BASE_MAKEUP,
        observations=[],
        exact_constraints=[
            CategoryDraft(value=TopicCode.BASE_MAKEUP),
        ],
        preference_drafts=[
            PreferenceDraft(
                field_key="finish",
                value="柔雾感",
                preference_kind="concept",
                concept_id="finish.matte",
                polarity="prefer",
            ),
        ],
        semantic_proposals=[],
        signal_trace=[],
        image_references=[],
        uncertainties=[],
        confidence=1.0,
    )
    flow = compose_text_recommendation_orchestrator(
        subset,
        product_assets=real_product_assets,
        conversation_state=conversation_state,
        selection_facts=ThreeBaseSelectionFacts(),
        concept_reader=SelectionParentConceptReader((projection,)),
        understanding=RecordingUnderstandingPort(understanding),
    )

    events = list(flow.stream(_turn("想要柔雾感粉底")))
    decision = next(
        event for event in events if event.event == "decision_process"
    )
    reason = next(
        event for event in events if event.event == "message"
    )

    matched = next(
        slot
        for slot in decision.data.concept_slots
        if slot.match_status == "matched"
    )
    assert matched.product_id == 82
    assert matched.source_refs == [source_ref]
    assert set(matched.source_refs) <= set(decision.data.evidence_refs)
    assert "现有资料" in reason.data.content
    assert "哑光柔雾肌" in reason.data.content
    assert "finish.matte" not in reason.data.content
    assert "不代表效果更强" in reason.data.content


def test_prior_image_similarity_uses_normal_recommendation_and_excludes_anchor(
    real_reader,
    real_product_assets,
    conversation_state,
    tmp_path: Path,
) -> None:
    subset = _subset_reader(real_reader, tmp_path, (53, 55))
    source_refs = (
        "urn:test:image-similarity:53",
        "urn:test:image-similarity:55",
    )
    projection = SelectionConceptProjection.model_validate(
        {
            "candidate_id": candidate_id_for(
                profile="suncare",
                field_key="texture",
                normalized_value="轻薄",
                product_ids=(53, 55),
                rank_strengths=(1,),
                source_refs=source_refs,
            ),
            "profile": "suncare",
            "field_key": "texture",
            "normalized_value": "轻薄",
            "product_ids": [53, 55],
            "rank_strengths": [1],
            "source_refs": list(source_refs),
            "concept_id": "texture.lightweight",
            "stance": "supports",
            "comparability": "binary",
            "order_value": None,
            "rationale": "测试审核过的图片锚点父概念投影。",
        },
        strict=True,
    )
    flow = compose_text_recommendation_orchestrator(
        subset,
        product_assets=real_product_assets,
        conversation_state=conversation_state,
        selection_facts=ImageSimilaritySelectionFacts(),
        concept_reader=SelectionParentConceptReader((projection,)),
        understanding=RecordingUnderstandingPort(
            _fragrance_understanding()
        ),
    )
    confirmed_images = (
        ConfirmedImageProductRef(
            image_ordinal=1,
            product_id=55,
        ),
        ConfirmedImageProductRef(
            image_ordinal=2,
            product_id=53,
        ),
    )
    conversation_state.save(
        ConversationSnapshot(
            session_id="s-1",
            version=1,
            has_image_delivery=True,
            focus_state=FocusState(
                active_processor="image_identity",
                current_product_id=None,
                confirmed_image_products=confirmed_images,
            ),
        ),
        expected_version=0,
    )
    understanding = StructuredUnderstanding(
        goal=UnderstandingGoal.IMAGE_SIMILARITY,
        topic=None,
        observations=[],
        exact_constraints=[
            BudgetDraft(maximum=Decimal("130")),
        ],
        semantic_proposals=[],
        signal_trace=[],
        references=[
            ReferenceDraft(
                kind="image_ordinal",
                ordinal=2,
            )
        ],
        image_references=[],
        uncertainties=[],
        confidence=1.0,
        question_meaning="以第二张图片商品为方向找预算内同类项",
    )
    binding = ResolvedProductBinding(
        product_id=53,
        variant_scope=None,
        source_text="image_ordinal:2",
    )

    events = list(
        flow.stream_understanding(
            _turn(
                "照第二张找一百三十元内的相似款",
                conversation_version=1,
            ),
            understanding=understanding,
            route_decision=UnifiedRouteDecision(
                processor="recommendation",
                continuity="continue",
                focus_source="confirmed_image",
                product_bindings=(binding,),
            ),
            product_bindings=(binding,),
        )
    )

    assert not any(event.event == "error" for event in events)
    intent = next(event for event in events if event.event == "intent")
    assert intent.data.mode == "image_recommend"
    products = next(
        event for event in events if event.event == "products"
    )
    assert [card.product_id for card in products.data.cards] == [55]
    decision = next(
        event for event in events if event.event == "decision_process"
    )
    matched = next(
        slot
        for slot in decision.data.concept_slots
        if slot.match_status == "matched"
    )
    assert matched.concept_id == "texture.lightweight"
    presentation = next(
        event
        for event in events
        if event.event == "presentation_contract"
    )
    assert presentation.data.mode == "image_recommendation"
    end = next(event for event in events if event.event == "end")
    assert end.data.conversation_version == 2
    stored = conversation_state.load("s-1")
    assert stored is not None
    assert stored.version == 2
    assert stored.focus_state is not None
    assert stored.focus_state.confirmed_image_products == confirmed_images


def test_image_similarity_empty_budget_result_commits_one_version(
    real_reader,
    real_product_assets,
    conversation_state,
    tmp_path: Path,
) -> None:
    subset = _subset_reader(real_reader, tmp_path, (53, 55))
    flow = compose_text_recommendation_orchestrator(
        subset,
        product_assets=real_product_assets,
        conversation_state=conversation_state,
        understanding=RecordingUnderstandingPort(
            _fragrance_understanding()
        ),
    )
    confirmed_image = ConfirmedImageProductRef(
        image_ordinal=1,
        product_id=53,
    )
    conversation_state.save(
        ConversationSnapshot(
            session_id="s-1",
            version=1,
            has_image_delivery=True,
            focus_state=FocusState(
                active_processor="image_identity",
                current_product_id=53,
                confirmed_image_products=(confirmed_image,),
            ),
        ),
        expected_version=0,
    )
    understanding = StructuredUnderstanding(
        goal=UnderstandingGoal.IMAGE_SIMILARITY,
        topic=TopicCode.SUNSCREEN,
        observations=[],
        exact_constraints=[
            CategoryDraft(value=TopicCode.SUNSCREEN),
            BudgetDraft(maximum=Decimal("80")),
        ],
        semantic_proposals=[],
        signal_trace=[],
        references=[
            ReferenceDraft(
                kind="image_ordinal",
                ordinal=1,
            )
        ],
        image_references=[],
        uncertainties=[],
        confidence=1.0,
        question_meaning="以图片商品为方向找八十元内同类项",
    )
    binding = ResolvedProductBinding(
        product_id=53,
        variant_scope=None,
        source_text="image_ordinal:1",
    )

    events = list(
        flow.stream_understanding(
            _turn(
                "以它为方向找八十元内同类防晒",
                conversation_version=1,
            ),
            understanding=understanding,
            route_decision=UnifiedRouteDecision(
                processor="recommendation",
                continuity="continue",
                focus_source="confirmed_image",
                product_bindings=(binding,),
            ),
            product_bindings=(binding,),
        )
    )

    assert not any(event.event == "error" for event in events)
    products = next(
        event for event in events if event.event == "products"
    )
    assert products.data.cards == []
    end = next(event for event in events if event.event == "end")
    assert end.data.conversation_version == 2
    stored = conversation_state.load("s-1")
    assert stored is not None
    assert stored.version == 2
    assert stored.empty_result is True
    assert stored.candidates == ()
    assert stored.focus_state is not None
    assert stored.focus_state.confirmed_image_products == (
        confirmed_image,
    )


def test_text_recommendation_empty_exclusion_result_commits_one_version(
    real_reader,
    real_product_assets,
    conversation_state,
    tmp_path: Path,
) -> None:
    subset = _subset_reader(real_reader, tmp_path, (38, 91))
    understanding = StructuredUnderstanding(
        goal=UnderstandingGoal.RECOMMENDATION,
        topic=TopicCode.SERUM,
        observations=[],
        exact_constraints=[
            CategoryDraft(value=TopicCode.SERUM),
            SkinDraft(value=SkinTarget.SENSITIVE),
            EfficacyDraft(value=EfficacyTarget.REPAIR),
            ExclusionDraft(value="酒精"),
        ],
        semantic_proposals=[],
        signal_trace=[],
        references=[],
        image_references=[],
        uncertainties=[],
        confidence=1.0,
        question_meaning=None,
    )
    flow = compose_text_recommendation_orchestrator(
        subset,
        product_assets=real_product_assets,
        conversation_state=conversation_state,
        understanding=RecordingUnderstandingPort(understanding),
    )

    events = list(
        flow.stream_understanding(
            _turn(
                "给我挑修护精华，敏感皮，先排除酒精",
                conversation_version=0,
            ),
            understanding=understanding,
            route_decision=UnifiedRouteDecision(
                processor="recommendation",
                continuity="replace_task",
                focus_source="none",
            ),
            product_bindings=(),
        )
    )

    products = next(
        event for event in events if event.event == "products"
    )
    assert products.data.cards == []
    end = next(event for event in events if event.event == "end")
    assert end.data.conversation_version == 1
    stored = conversation_state.load("s-1")
    assert stored is not None
    assert stored.version == 1
    assert stored.empty_result is True
    assert stored.query_context is not None
    assert stored.query_context.exclusions == ("酒精",)


def test_image_similarity_respects_requested_alternative_count(
    real_reader,
    real_product_assets,
    conversation_state,
    tmp_path: Path,
) -> None:
    subset = _subset_reader(real_reader, tmp_path, (51, 53, 54, 55))
    flow = compose_text_recommendation_orchestrator(
        subset,
        product_assets=real_product_assets,
        conversation_state=conversation_state,
        understanding=RecordingUnderstandingPort(
            _fragrance_understanding()
        ),
    )
    confirmed_image = ConfirmedImageProductRef(
        image_ordinal=1,
        product_id=53,
    )
    conversation_state.save(
        ConversationSnapshot(
            session_id="s-1",
            version=1,
            has_image_delivery=True,
            focus_state=FocusState(
                active_processor="image_identity",
                current_product_id=53,
                confirmed_image_products=(confirmed_image,),
            ),
        ),
        expected_version=0,
    )
    understanding = StructuredUnderstanding(
        goal=UnderstandingGoal.IMAGE_SIMILARITY,
        topic=TopicCode.SUNSCREEN,
        observations=[],
        exact_constraints=[
            CategoryDraft(value=TopicCode.SUNSCREEN),
            BudgetDraft(maximum=Decimal("150")),
        ],
        semantic_proposals=[],
        signal_trace=[],
        references=[
            ReferenceDraft(
                kind="image_ordinal",
                ordinal=1,
            )
        ],
        image_references=[],
        uncertainties=[],
        confidence=1.0,
        question_meaning="以图片商品为方向找两款同类项",
    )
    binding = ResolvedProductBinding(
        product_id=53,
        variant_scope=None,
        source_text="image_ordinal:1",
    )

    events = list(
        flow.stream_understanding(
            _turn(
                "按它的方向找两款一百五十元内相似防晒",
                conversation_version=1,
            ),
            understanding=understanding,
            route_decision=UnifiedRouteDecision(
                processor="recommendation",
                continuity="continue",
                focus_source="confirmed_image",
                product_bindings=(binding,),
            ),
            product_bindings=(binding,),
        )
    )

    products = next(
        event for event in events if event.event == "products"
    )
    product_ids = [
        card.product_id for card in products.data.cards
    ]
    assert len(product_ids) == 2
    assert 53 not in product_ids


def test_text_recommendation_respects_requested_result_count(
    real_reader,
    real_product_assets,
    conversation_state,
) -> None:
    flow = compose_text_recommendation_orchestrator(
        real_reader,
        product_assets=real_product_assets,
        conversation_state=conversation_state,
        understanding=RecordingUnderstandingPort(
            _fragrance_understanding()
        ),
    )
    understanding = StructuredUnderstanding(
        goal=UnderstandingGoal.RECOMMENDATION,
        topic=TopicCode.SUNSCREEN,
        observations=[],
        exact_constraints=[
            CategoryDraft(value=TopicCode.SUNSCREEN),
            BudgetDraft(maximum=Decimal("200")),
        ],
        semantic_proposals=[],
        signal_trace=[],
        references=[],
        image_references=[],
        uncertainties=[],
        confidence=1.0,
    )

    events = list(
        flow.stream_understanding(
            _turn("给我两支两百内的防晒"),
            understanding=understanding,
            route_decision=UnifiedRouteDecision(
                processor="recommendation",
                continuity="replace_task",
                focus_source="none",
            ),
            product_bindings=(),
        )
    )

    products = next(
        event for event in events if event.event == "products"
    )
    assert len(products.data.cards) == 2


def test_route_budget_clarification_preserves_pending_recommendation(
    real_reader,
    real_product_assets,
    conversation_state,
) -> None:
    message = "想看敏感肌修护精华，预算大概五百吧"
    understanding = exact_echo_understanding().understand(
        message,
        context=resolve_semantic_context(
            conversation_version=0,
            snapshot=None,
        ),
    )
    flow = compose_text_recommendation_orchestrator(
        real_reader,
        product_assets=real_product_assets,
        conversation_state=conversation_state,
    )

    events = list(
        flow.stream_understanding(
            _turn(message),
            understanding=understanding,
            route_decision=UnifiedRouteDecision(
                processor="clarification",
                continuity="replace_task",
                focus_source="none",
                clarification=(
                    "你说的“预算大概五百”"
                    "是指 450 到 550 元吗？"
                ),
                clarification_code=ClarificationCode.BUDGET,
            ),
            product_bindings=(),
        )
    )

    clarify = next(event for event in events if event.event == "clarify")
    pending = clarify.data.pending_turn
    assert pending is not None
    assert pending.gap is ClarificationCode.BUDGET
    assert pending.source_message == message
    assert pending.resume_context.category == "serum"
    assert pending.resume_context.skin == "sensitive"
    assert pending.resume_context.efficacy == "repair"
    assert pending.proposed_budget is not None
    assert pending.proposed_budget.minimum == Decimal("450")
    assert pending.proposed_budget.maximum == Decimal("550")


def test_application_layer_does_not_import_siliconflow_adapter() -> None:
    source = (
        Path(__file__).resolve().parents[3]
        / "app"
        / "guide"
        / "application"
        / "text_recommendation_flow.py"
    ).read_text(encoding="utf-8")
    assert "siliconflow" not in source.casefold()
    assert "httpx" not in source.casefold()


def test_application_does_not_mutate_task_plan_with_profile_values() -> None:
    source_path = (
        Path(__file__).resolve().parents[3]
        / "app"
        / "guide"
        / "application"
        / "text_recommendation_flow.py"
    )
    tree = ast.parse(
        source_path.read_text(encoding="utf-8"),
        filename=str(source_path),
    )

    assert not any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "_fill_profile_skin"
        for node in ast.walk(tree)
    )


def _turn(
    message: str,
    *,
    conversation_version: int = 0,
    profile_owner: ProfileOwnerRef | None = None,
) -> UserTurn:
    values = {
        "session_id": "s-1",
        "message": message,
        "image_bundle_id": None,
        "conversation_version": conversation_version,
    }
    if profile_owner is not None:
        values["profile_owner"] = profile_owner
    return UserTurn(**values)


def _profile_owner(subject_id: str) -> ProfileOwnerRef:
    return ProfileOwnerRef(
        scope="authenticated_user",
        subject_id=subject_id,
    )


class TrackingSessionLocks:
    def __init__(self) -> None:
        self.held = False

    @contextmanager
    def hold(self, session_id: str) -> Iterator[None]:
        assert session_id
        assert not self.held
        self.held = True
        try:
            yield
        finally:
            self.held = False


def test_stream_yields_start_before_catalog_work(orchestrator) -> None:
    stream = orchestrator.stream(_turn("500 内适合油敏肌的防晒"))
    assert isinstance(stream, Iterator)
    first = next(stream)
    assert first.event == "start"


def test_end_event_requires_conversation_version() -> None:
    event = EndEvent(data=EndData(conversation_version=2))
    assert event.data.conversation_version == 2


def test_decision_process_accepts_strict_selection_slot_payload() -> None:
    assert hasattr(sse_events, "SelectionSlotData")

    slot = sse_events.SelectionSlotData(
        product_id=55,
        field_key="suitable_skin",
        requested_value="敏感肌",
        matched_value="敏感肌",
        match_status="matched",
        rank_strength=1,
        source_refs=["evidence-a"],
        attribution="merchant_claim",
    )
    data = sse_events.DecisionProcessData(
        ordered_product_ids=[55],
        winner_status="SELECTED",
        evidence_refs=["facet=suitable_skin:敏感肌"],
        selection_slots=[slot],
    )

    assert data.selection_slots == [slot]


def test_recommendation_passes_safety_strength_explicitly(
    real_reader,
    real_product_assets,
    conversation_state,
    monkeypatch,
) -> None:
    understanding = StructuredUnderstanding(
        goal=UnderstandingGoal.RECOMMENDATION,
        topic=TopicCode.SUNSCREEN,
        observations=[],
        exact_constraints=[
            CategoryDraft(value=TopicCode.SUNSCREEN),
        ],
        preference_drafts=[
            PreferenceDraft(
                field_key="suitable_skin",
                value="敏感肌",
            )
        ],
        semantic_proposals=[],
        signal_trace=[],
        references=[],
        image_references=[],
        uncertainties=[],
        confidence=0.95,
        safety_sensitive=True,
    )
    orchestrator = compose_text_recommendation_orchestrator(
        real_reader,
        product_assets=real_product_assets,
        conversation_state=conversation_state,
        understanding=RecordingUnderstandingPort(understanding),
    )
    from app.guide.application import text_recommendation_flow as flow

    original = flow.decide_recommendation
    observed: list[bool] = []

    def recording_decision(*args, **kwargs):
        observed.append(kwargs["safety_sensitive"])
        return original(*args, **kwargs)

    monkeypatch.setattr(
        flow,
        "decide_recommendation",
        recording_decision,
    )

    events = list(
        orchestrator.stream(
            _turn("我的皮肤很敏感，一定不能刺激，推荐防晒")
        )
    )

    assert not any(item.event == "error" for item in events)
    assert observed == [True]


def test_full_query_has_contract_order_and_no_false_winner(
    orchestrator,
) -> None:
    events = list(
        orchestrator.stream(_turn("500 内适合油敏肌的防晒"))
    )
    names = [item.event for item in events]
    assert names[0] == "start"
    assert names[-1] == "end"
    assert names.count("end") == 1
    assert names.index("decision_process") < names.index("answer_contract")
    assert names.index("answer_contract") < names.index(
        "card_display_contract"
    )
    assert names.index("card_display_contract") < names.index("products")
    products = next(item for item in events if item.event == "products")
    assert [card.product_id for card in products.data.cards] == [101, 26, 52]
    decision = next(
        item for item in events if item.event == "decision_process"
    )
    assert decision.data.ordered_product_ids == [101, 26, 52]
    assert decision.data.winner_status == "INSUFFICIENT_FOR_WINNER"
    card_display = next(
        item
        for item in events
        if item.event == "card_display_contract"
    )
    assert card_display.data.model_dump(mode="json") == {
        "mode": "recommendation",
        "visible_product_ids": [101, 26, 52],
        "max_cards": 3,
        "reason": "recommendation",
    }
    messages = [item.data.content for item in events if item.event == "message"]
    assert messages
    assert all(content.strip() for content in messages)


def test_selection_slots_survive_ordinal_followup(
    real_reader,
    real_product_assets,
    conversation_state,
) -> None:
    root = Path(__file__).resolve().parents[3]
    category_facts = build_category_fact_reader(
        real_reader,
        repo_root=root,
    )
    product_evidence = build_product_evidence_reader(root)
    selection_facts = build_selection_fact_reader(
        category_facts=category_facts,
        product_evidence=product_evidence,
    )
    understanding = StructuredUnderstanding(
        goal=UnderstandingGoal.RECOMMENDATION,
        topic=TopicCode.SUNSCREEN,
        observations=[],
        exact_constraints=[
            CategoryDraft(value=TopicCode.SUNSCREEN),
        ],
        preference_drafts=[
            PreferenceDraft(
                field_key="suitable_skin",
                value="敏感肌",
            )
        ],
        semantic_proposals=[],
        signal_trace=[],
        references=[],
        image_references=[],
        uncertainties=[],
        confidence=0.95,
        safety_sensitive=False,
    )
    orchestrator = compose_text_recommendation_orchestrator(
        real_reader,
        product_assets=real_product_assets,
        conversation_state=conversation_state,
        category_fact_port=category_facts,
        selection_facts=selection_facts,
        understanding=RecordingUnderstandingPort(understanding),
    )

    first = list(
        orchestrator.stream(_turn("想找敏感肌适用的防晒"))
    )
    first_products = next(
        item for item in first if item.event == "products"
    )
    first_decision = next(
        item for item in first if item.event == "decision_process"
    )
    selected_product_id = first_products.data.cards[1].product_id
    expected_slots = [
        item.model_dump(mode="json")
        for item in first_decision.data.selection_slots
        if item.product_id == selected_product_id
    ]

    followup = list(
        orchestrator.stream(
            _turn("第二个怎么样", conversation_version=1)
        )
    )
    followup_decision = next(
        item for item in followup
        if item.event == "decision_process"
    )

    assert expected_slots
    assert [
        item.model_dump(mode="json")
        for item in followup_decision.data.selection_slots
    ] == expected_slots
    assert all(
        item.source_refs
        for item in first_decision.data.selection_slots
        if item.match_status == "matched"
    )


def test_normal_recommendation_keeps_claims_and_reviews_out_of_main_copy(
    real_reader,
    real_product_assets,
    conversation_state,
) -> None:
    root = Path(__file__).resolve().parents[3]
    category_facts = build_category_fact_reader(
        real_reader,
        repo_root=root,
    )
    orchestrator = compose_text_recommendation_orchestrator(
        real_reader,
        product_assets=real_product_assets,
        conversation_state=conversation_state,
        category_fact_port=category_facts,
        merchant_claims=category_facts.claims,
        review_evidence=build_review_evidence_reader(root),
        understanding=exact_echo_understanding(),
    )

    events = list(
        orchestrator.stream(_turn("97 内适合油敏肌的防晒"))
    )
    claims = next(
        item for item in events if item.event == "merchant_claims"
    )
    reviews = next(
        item for item in events if item.event == "review_evidence"
    )
    message = next(
        item.data.content
        for item in events
        if item.event == "message"
    )

    assert {item.product_id for item in claims.data.claims} <= {
        55,
        57,
        54,
    }
    assert any(
        item.product_id == 55
        and item.source_label == "商家宣称"
        and item.verification_status == "未经独立核实"
        and item.allowed_use == "soft_rank_and_display"
        for item in claims.data.claims
    )
    assert any(
        item.claim_scope == "safety_transcript"
        and item.allowed_use == "display_only"
        for item in claims.data.claims
    )
    assert sorted(
        len(item.evidence) for item in reviews.data.results
    ) == [0, 0, 2]
    assert "商家宣称参考" not in message
    assert "未经独立核实" not in message
    assert "已批准评论原文" not in message
    assert "多数评论" not in message
    names = [item.event for item in events]
    assert names.index("merchant_claims") < names.index(
        "presentation_contract"
    )
    assert names.index("review_evidence") < names.index(
        "presentation_contract"
    )
    assert names.index("presentation_contract") < names.index("message")


def test_merchant_projection_keeps_all_reviewed_ordinary_dimensions(
    real_reader,
) -> None:
    from app.guide.application.text_recommendation_flow import (
        _project_merchant_claims,
    )

    root = Path(__file__).resolve().parents[3]
    category_facts = build_category_fact_reader(
        real_reader,
        repo_root=root,
    )

    projected = _project_merchant_claims(
        category_facts.claims,
        product_ids=(52,),
        constraints=[],
    )
    ordinary = [
        item for item in projected if item.claim_scope == "ordinary"
    ]

    assert len(ordinary) == 5
    assert all(item.normalized_value for item in ordinary)
    assert {
        item.field_key for item in ordinary
    } >= {
        "texture",
        "film_speed",
        "tone_effect",
        "finish",
    }


def test_complete_consumer_self_report_becomes_one_numeric_proof(
    real_reader,
) -> None:
    from app.guide.application.text_recommendation_flow import (
        _presentation_proof_points,
    )

    root = Path(__file__).resolve().parents[3]
    retriever = ProductEvidenceRetriever(
        build_product_evidence_reader(root)
    )
    packet = retriever.retrieve(
        EvidenceQuery(
            product_ids=(58,),
            raw_question="轻薄不厚重、清爽不油腻的消费者测试",
            question_meaning="询问轻薄清爽的消费者认同",
            safety_sensitive=False,
        )
    )
    event = sse_events.ProductEvidenceEvent(
        data=sse_events.ProductEvidenceData(packet=packet)
    )

    proof_points = _presentation_proof_points(event)

    assert len(proof_points) == 1
    assert proof_points[0].product_id == 58
    assert proof_points[0].kind == "numeric"
    assert proof_points[0].label == "用户测试"
    assert proof_points[0].display_value.startswith("商家引用：")
    assert "62名" in proof_points[0].display_value
    assert "连续2周" in proof_points[0].display_value
    assert "消费者认同" in proof_points[0].display_value
    assert "100%" in proof_points[0].display_value


def test_repair_serum_real_data_contract(orchestrator) -> None:
    events = list(
        orchestrator.stream(_turn("500 元内敏感肌修护精华"))
    )
    products = next(item for item in events if item.event == "products")
    assert [card.product_id for card in products.data.cards] == [38, 91]
    card_display = next(
        item
        for item in events
        if item.event == "card_display_contract"
    )
    assert card_display.data.visible_product_ids == (38, 91)
    assert card_display.data.max_cards == 2
    assert card_display.data.mode == "recommendation"
    assert all(
        card.matched_efficacies == ["修护"]
        for card in products.data.cards
    )
    assert all(
        card.category == "精华"
        for card in products.data.cards
    )
    message = next(item for item in events if item.event == "message")
    assert "敏感肌适配信息还不够完整" in message.data.content


def test_outdoor_scenario_emits_typed_evidence_without_changing_cards(
    orchestrator,
) -> None:
    events = list(
        orchestrator.stream(
            _turn("500 元内长时间户外防晒")
        )
    )
    names = [item.event for item in events]

    assert names == [
        "start",
        "stage",
        "intent",
        "stage",
        "stage",
        "scenario_evidence",
        "review_evidence",
        "pitfalls",
        "decision_process",
        "answer_contract",
        "card_display_contract",
        "products",
        "presentation_contract",
        "message",
        "end",
    ]
    scenario = next(
        item for item in events if item.event == "scenario_evidence"
    )
    assert [item.product_id for item in scenario.data.records] == [
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
    assert [
        item.field.value
        for item in scenario.data.records[:3]
    ] == ["spf_pa", "water_resistance", "usage"]
    assert all(
        item.state.value == "unknown"
        for item in scenario.data.records[:3]
    )
    known_spf_ids = [
        item.product_id
        for item in scenario.data.records
        if item.field.value == "spf_pa"
        and item.state.value == "known"
    ]
    assert known_spf_ids == [26, 52]

    reviews = next(
        item for item in events if item.event == "review_evidence"
    )
    assert reviews.data.approved_source_count == 6
    assert [
        item.product_id for item in reviews.data.results
    ] == [101, 26, 52]
    assert [
        len(item.evidence) for item in reviews.data.results
    ] == [0, 0, 0]
    assert all(
        item.verified_absence is not None
        for item in reviews.data.results
    )
    assert reviews.data.summaries == []
    assert {
        evidence.product_id
        for result in reviews.data.results
        for evidence in result.evidence
    } == set()

    pitfalls = next(
        item for item in events if item.event == "pitfalls"
    )
    assert pitfalls.data.pitfalls == []
    products = next(
        item for item in events if item.event == "products"
    )
    assert [card.product_id for card in products.data.cards] == [
        101,
        26,
        52,
    ]
    card_display = next(
        item
        for item in events
        if item.event == "card_display_contract"
    )
    assert card_display.data.visible_product_ids == (101, 26, 52)
    assert card_display.data.max_cards == 3


def test_outdoor_budget_band_keeps_per_product_review_absence(
    orchestrator,
) -> None:
    events = list(
        orchestrator.stream(
            _turn("300到500元长时间户外防晒")
        )
    )

    reviews = next(
        item for item in events if item.event == "review_evidence"
    )
    products = next(
        item for item in events if item.event == "products"
    )
    card_display = next(
        item
        for item in events
        if item.event == "card_display_contract"
    )
    pitfalls = next(
        item for item in events if item.event == "pitfalls"
    )

    assert [card.product_id for card in products.data.cards] == [101, 26]
    assert card_display.data.visible_product_ids == (101, 26)
    assert reviews.data.approved_source_count == 6
    assert [
        item.product_id for item in reviews.data.results
    ] == [101, 26]
    assert reviews.data.summaries == []
    assert all(
        not item.evidence and item.verified_absence is not None
        for item in reviews.data.results
    )
    assert pitfalls.data.pitfalls == []


def test_sensitive_period_scenario_applies_before_ranking_and_emits_pitfalls(
    orchestrator,
) -> None:
    events = list(
        orchestrator.stream(
            _turn("500 元内敏感期修护精华")
        )
    )
    decision = next(
        item for item in events if item.event == "decision_process"
    )
    products = next(
        item for item in events if item.event == "products"
    )
    scenario = next(
        item for item in events if item.event == "scenario_evidence"
    )
    pitfalls = next(
        item for item in events if item.event == "pitfalls"
    )

    assert "skin=sensitive" in decision.data.evidence_refs
    assert "efficacy=repair" in decision.data.evidence_refs
    assert decision.data.ordered_product_ids == [38, 91]
    assert [card.product_id for card in products.data.cards] == [38, 91]
    sensitive_records = [
        item
        for item in scenario.data.records
        if item.field.value == "suitable_skin"
    ]
    assert [item.product_id for item in sensitive_records] == [38, 91]
    assert {
        item.field.value for item in scenario.data.records
    } == {"efficacy", "suitable_skin"}
    assert [item.product_id for item in pitfalls.data.pitfalls] == [38, 91]
    assert all(
        item.severity.value == "medium"
        for item in pitfalls.data.pitfalls
    )
    assert all(
        item.claim_kind.value == "suitability"
        for item in pitfalls.data.pitfalls
    )
    assert all(
        item.evidence_refs
        and all(
            reference.startswith("pitfall_evidence:canonical:")
            for reference in item.evidence_refs
        )
        for item in pitfalls.data.pitfalls
    )


def test_repair_scenario_uses_budget_proximity_for_equal_fits(
    orchestrator,
) -> None:
    events = list(
        orchestrator.stream(_turn("500 元内修护期精华"))
    )
    products = next(
        item for item in events if item.event == "products"
    )

    assert [card.product_id for card in products.data.cards] == [38, 91]


def test_typed_efficacy_withdrawal_cannot_be_readded_by_scenario_parser(
    real_reader,
    real_product_assets,
    conversation_state,
) -> None:
    second_message = "修护不再作为硬条件，接下来保湿优先"
    understanding = SequenceUnderstandingPort((
        StructuredUnderstanding(
            goal=UnderstandingGoal.RECOMMENDATION,
            topic=TopicCode.SERUM,
            observations=[],
            exact_constraints=[
                CategoryDraft(value=TopicCode.SERUM),
                BudgetDraft(maximum=Decimal("300")),
                EfficacyDraft(value=EfficacyTarget.REPAIR),
            ],
            semantic_proposals=[],
            signal_trace=[],
            image_references=[],
            uncertainties=[],
            confidence=1.0,
            semantic_authoritative=True,
        ),
        StructuredUnderstanding(
            goal=UnderstandingGoal.RECOMMENDATION,
            topic=TopicCode.SERUM,
            observations=[],
            exact_constraints=[
                CategoryDraft(value=TopicCode.SERUM),
                BudgetDraft(maximum=Decimal("300")),
            ],
            preference_drafts=[
                PreferenceDraft(
                    field_key="efficacy",
                    value="保湿",
                    preference_kind="concept",
                    concept_id="efficacy.hydration",
                )
            ],
            constraint_changes=[
                ConstraintChangeDraft(
                    parent_concept="efficacy",
                    requested_change="remove",
                    value="repair",
                    source_span=SourceSpan(start=0, end=2),
                )
            ],
            semantic_proposals=[],
            signal_trace=[],
            image_references=[],
            uncertainties=[],
            confidence=1.0,
            semantic_authoritative=True,
        ),
    ))
    orchestrator = compose_text_recommendation_orchestrator(
        real_reader,
        product_assets=real_product_assets,
        conversation_state=conversation_state,
        understanding=understanding,
        concept_reader=build_selection_parent_concept_reader(
            Path(__file__).resolve().parents[3]
        ),
    )

    list(orchestrator.stream(_turn("三百元内修护精华")))
    events = list(
        orchestrator.stream(
            _turn(second_message, conversation_version=1)
        )
    )
    snapshot = conversation_state.load("s-1")

    assert not any(event.event == "error" for event in events)
    assert not any(
        event.event == "scenario_evidence"
        for event in events
    )
    assert snapshot is not None
    assert snapshot.query_context is not None
    assert snapshot.query_context.efficacy is None
    assert [
        item.concept_id for item in snapshot.query_context.concepts
    ] == ["efficacy.hydration"]


def test_scenario_failure_remains_terminal_without_partial_evidence(
    broken_orchestrator,
) -> None:
    events = list(
        broken_orchestrator.stream(
            _turn("500 元内长时间户外防晒")
        )
    )

    assert [item.event for item in events] == ["start", "error"]


def test_real_generic_skin_claims_remain_unknown_for_dry_skin(
    orchestrator,
) -> None:
    events = list(
        orchestrator.stream(_turn("500元内干性修护精华"))
    )
    products = next(item for item in events if item.event == "products")
    decision = next(
        item for item in events if item.event == "decision_process"
    )

    assert [card.product_id for card in products.data.cards] == [38, 91]
    assert all(card.skin_match == "unknown" for card in products.data.cards)
    assert decision.data.winner_status == "INSUFFICIENT_FOR_WINNER"
    assert "skin=dry" in decision.data.evidence_refs


def test_recommendation_saves_only_visible_candidates(
    orchestrator,
    conversation_state,
) -> None:
    events = list(
        orchestrator.stream(
            _turn("500 内适合油敏肌的防晒")
        )
    )
    snapshot = conversation_state.load("s-1")

    assert snapshot is not None
    assert [item.product_id for item in snapshot.candidates] == [
        101, 26, 52
    ]
    assert snapshot.query_context.category == "sunscreen"
    assert snapshot.query_context.budget_maximum == 500
    assert snapshot.query_context.skin == "oily_sensitive"
    assert events[-1].event == "end"
    assert events[-1].data.conversation_version == 1


def test_semantic_budget_revision_without_exact_confirmation_keeps_state(
    real_reader,
    real_product_assets,
    conversation_state,
) -> None:
    semantic = BudgetRevisionProposalPort()
    orchestrator = compose_text_recommendation_orchestrator(
        real_reader,
        product_assets=real_product_assets,
        conversation_state=conversation_state,
        understanding=ParallelUnderstanding(semantic=semantic),
    )
    list(orchestrator.stream(_turn("500元内推荐防晒")))
    before = conversation_state.load("s-1")

    events = list(
        orchestrator.stream(
            _turn(
                "这个条件我想调整一下",
                conversation_version=1,
            )
        )
    )
    after = conversation_state.load("s-1")

    assert before is not None
    assert before.version == 1
    assert before.query_context is not None
    assert before.query_context.budget_maximum == Decimal("500")
    assert [event.event for event in events] == [
        "start",
        "stage",
        "intent",
        "clarify",
        "end",
    ]
    assert not any(
        event.event in {"decision_process", "products"}
        for event in events
    )
    assert after == before
    assert semantic.calls == 2


def test_code_owned_budget_replace_retains_repeated_exclusion(
    real_reader,
    real_product_assets,
    conversation_state,
    monkeypatch,
) -> None:
    second_message = "预算改成三百以内，而且还是不要含酒精的呢"
    semantic = SequenceSemanticPort(
        (
            SemanticIntentProposal(
                goal=SemanticGoal.RECOMMENDATION,
                topic=TopicCode.SUNSCREEN,
                concerns=(),
                observations=(),
                references=(),
                confidence=0.99,
                clarification_hint=None,
            ),
            SemanticIntentProposal(
                goal=SemanticGoal.FOLLOWUP,
                topic=TopicCode.SUNSCREEN,
                concerns=(),
                observations=(),
                references=(
                    SemanticReference(
                        kind="previous_constraint",
                        raw_text="预算",
                        start=0,
                        end=2,
                    ),
                ),
                confidence=0.99,
                clarification_hint=None,
            ),
        )
    )
    orchestrator = compose_text_recommendation_orchestrator(
        real_reader,
        product_assets=real_product_assets,
        conversation_state=conversation_state,
        understanding=ParallelUnderstanding(semantic=semantic),
    )
    first = list(
        orchestrator.stream(
            _turn("500元内推荐防晒")
        )
    )
    before = conversation_state.load("s-1")
    assert before is not None
    assert before.query_context is not None
    conversation_state.save(
        before.model_copy(
            update={
                "version": 2,
                "query_context": before.query_context.model_copy(
                    update={"exclusions": ("酒精",)},
                    deep=True,
                ),
            },
            deep=True,
        ),
        expected_version=1,
    )

    from app.guide.application import text_recommendation_flow as flow

    original_decision = flow.decide_recommendation

    def decision_without_fixture_only_exclusion(*args, **kwargs):
        kwargs["constraints"] = [
            constraint
            for constraint in kwargs["constraints"]
            if not isinstance(constraint, ExclusionConstraint)
        ]
        return original_decision(*args, **kwargs)

    monkeypatch.setattr(
        flow,
        "decide_recommendation",
        decision_without_fixture_only_exclusion,
    )

    second = list(
        orchestrator.stream(
            _turn(second_message, conversation_version=2)
        )
    )
    stored = conversation_state.load("s-1")

    assert first[-1].data.conversation_version == 1
    assert not any(
        event.event in {"clarify", "error"} for event in second
    )
    assert stored is not None
    assert stored.version == 3
    assert stored.query_context is not None
    assert stored.query_context.budget_maximum == Decimal("300")
    assert stored.query_context.exclusions == ("酒精",)


def test_recommendation_first_binds_trusted_owner_on_initial_snapshot(
    orchestrator,
    conversation_state,
) -> None:
    owner = _profile_owner("profile_recommendation_0001")

    events = list(
        orchestrator.stream(
            _turn(
                "500 元内敏感肌修护精华",
                profile_owner=owner,
            )
        )
    )

    stored = conversation_state.load("s-1")
    assert not any(event.event == "error" for event in events)
    assert stored is not None
    assert stored.profile_owner == owner


@pytest.mark.parametrize(
    "first_owner",
    [None, _profile_owner("profile_recommendation_0001")],
    ids=["ownerless-cannot-be-claimed", "owner-mismatch"],
)
def test_recommendation_owner_change_fails_closed_without_owner_leak(
    orchestrator,
    conversation_state,
    first_owner: ProfileOwnerRef | None,
) -> None:
    requested_owner = _profile_owner("profile_recommendation_0002")
    list(
        orchestrator.stream(
            _turn(
                "500 元内敏感肌修护精华",
                profile_owner=first_owner,
            )
        )
    )
    before = conversation_state.load("s-1")

    events = list(
        orchestrator.stream(
            _turn(
                "500 元内敏感肌修护精华",
                conversation_version=1,
                profile_owner=requested_owner,
            )
        )
    )

    assert [event.event for event in events] == [
        "start",
        "intent",
        "clarify",
        "end",
    ]
    assert events[1].data.mode == "clarify"
    assert conversation_state.load("s-1") == before
    rendered = repr(
        [event.model_dump(mode="json") for event in events]
    )
    assert requested_owner.subject_id not in rendered
    if first_owner is not None:
        assert first_owner.subject_id not in rendered


def test_recommendation_from_consultation_only_snapshot_preserves_consultation(
    orchestrator,
    conversation_state,
) -> None:
    consultation = ConsultationSubstate(
        started_at_conversation_version=1,
        observations=(
            ConsultationObservation(
                code="post_cleanse_tightness",
                answer="yes",
                source_turn_id="turn_0000000000000001",
            ),
        ),
    )
    conversation_state.save(
        ConversationSnapshot(
            session_id="s-1",
            version=1,
            query_context=None,
            candidates=[],
            consultation=ConsultationSubstate(
                started_at_conversation_version=1,
                observations=[],
            ),
        ),
        expected_version=0,
    )
    conversation_state.save(
        ConversationSnapshot(
            session_id="s-1",
            version=2,
            query_context=None,
            candidates=[],
            consultation=consultation,
        ),
        expected_version=1,
    )

    events = list(
        orchestrator.stream(
            _turn(
                "500 元内敏感肌修护精华",
                conversation_version=2,
            )
        )
    )

    stored = conversation_state.load("s-1")
    assert not any(event.event == "error" for event in events)
    assert any(event.event == "products" for event in events)
    assert events[-1].data.conversation_version == 3
    assert stored is not None
    assert stored.version == 3
    assert stored.query_context is not None
    assert isinstance(stored.candidates, tuple)
    assert [item.product_id for item in stored.candidates] == [38, 91]
    assert stored.consultation == consultation


def test_closing_after_start_before_post_start_event_does_not_commit_snapshot(
    orchestrator,
    conversation_state,
) -> None:
    stream = orchestrator.stream(
        _turn("500 元内敏感肌修护精华")
    )
    assert next(stream).event == "start"
    stream.close()

    assert conversation_state.load("s-1") is None


def test_closing_after_message_keeps_committed_snapshot_consistent(
    orchestrator,
    conversation_state,
) -> None:
    stream = orchestrator.stream(
        _turn("500 元内敏感肌修护精华")
    )
    seen = []
    for event in stream:
        seen.append(event.event)
        if event.event == "message":
            break
    stream.close()

    snapshot = conversation_state.load("s-1")
    assert "message" in seen
    assert snapshot is not None
    assert snapshot.version == 1
    assert [item.product_id for item in snapshot.candidates] == [38, 91]


def test_candidate_followup_preserves_query_context(
    orchestrator,
    conversation_state,
) -> None:
    list(orchestrator.stream(_turn("500 元内敏感肌修护精华")))
    before = conversation_state.load("s-1")

    events = list(
        orchestrator.stream(
            _turn("第二款呢", conversation_version=1)
        )
    )
    after = conversation_state.load("s-1")

    assert before is not None
    assert after is not None
    assert after.query_context == before.query_context
    assert after.version == 2
    assert events[-1].data.conversation_version == 2


def test_second_item_how_is_it_uses_visible_candidate_without_reclarifying(
    orchestrator,
    conversation_state,
) -> None:
    first = list(
        orchestrator.stream(_turn("500 元内敏感肌修护精华"))
    )
    first_products = next(
        event for event in first if event.event == "products"
    )

    events = list(
        orchestrator.stream(
            _turn("第二个怎么样", conversation_version=1)
        )
    )
    focused = conversation_state.load("s-1")

    assert not any(
        event.event in {"clarify", "error"}
        for event in events
    )
    products = next(
        event for event in events if event.event == "products"
    )
    assert [card.product_id for card in products.data.cards] == [
        first_products.data.cards[1].product_id,
    ]
    assert focused is not None
    assert focused.focused_candidate_ordinal == 2


def test_ordinal_followup_sets_explicit_candidate_focus(
    orchestrator,
    conversation_state,
) -> None:
    list(orchestrator.stream(_turn("500 元内敏感肌修护精华")))
    initial = conversation_state.load("s-1")

    list(
        orchestrator.stream(
            _turn("第二款呢", conversation_version=1)
        )
    )
    focused = conversation_state.load("s-1")

    assert initial is not None
    assert initial.focused_candidate_ordinal is None
    assert focused is not None
    assert focused.version == 2
    assert focused.focused_candidate_ordinal == 2


def test_replacing_candidate_batch_clears_candidate_focus(
    orchestrator,
    conversation_state,
) -> None:
    list(orchestrator.stream(_turn("500 元内敏感肌修护精华")))
    list(
        orchestrator.stream(
            _turn("第二款呢", conversation_version=1)
        )
    )

    events = list(
        orchestrator.stream(
            _turn("500 元内推荐防晒", conversation_version=2)
        )
    )
    replaced = conversation_state.load("s-1")

    assert events[-1].data.conversation_version == 3
    assert replaced is not None
    assert replaced.query_context is not None
    assert replaced.query_context.category == "sunscreen"
    assert replaced.focused_candidate_ordinal is None


def test_closing_followup_after_message_keeps_committed_version_consistent(
    orchestrator,
    conversation_state,
) -> None:
    list(orchestrator.stream(_turn("500 元内敏感肌修护精华")))
    before = conversation_state.load("s-1")
    assert before is not None

    stream = orchestrator.stream(
        _turn("第二款呢", conversation_version=1)
    )
    seen = []
    for event in stream:
        seen.append(event.event)
        if event.event == "message":
            break
    stream.close()

    after = conversation_state.load("s-1")
    assert "message" in seen
    assert after is not None
    assert after.version == before.version + 1
    assert after.candidates == before.candidates
    assert after.query_context == before.query_context


def test_post_start_events_are_public_only_after_session_lock_release(
    real_reader,
    real_product_assets,
    conversation_state,
) -> None:
    locks = TrackingSessionLocks()
    orchestrator = compose_text_recommendation_orchestrator(
        real_reader,
        product_assets=real_product_assets,
        conversation_state=conversation_state,
        session_locks=locks,
        understanding=exact_echo_understanding(),
    )
    stream = orchestrator.stream(
        _turn("500 元内敏感肌修护精华")
    )

    assert next(stream).event == "start"
    assert not locks.held
    assert next(stream).event == "stage"
    assert not locks.held
    stream.close()


def test_ordinal_followup_uses_snapshot_without_retrieval(
    orchestrator,
    monkeypatch,
) -> None:
    list(orchestrator.stream(_turn("500 元内敏感肌修护精华")))

    def forbidden_retrieval(*args, **kwargs):
        raise AssertionError("followup must not retrieve")

    monkeypatch.setattr(
        "app.guide.application.text_recommendation_flow.retrieve_candidates",
        forbidden_retrieval,
    )
    events = list(
        orchestrator.stream(
            _turn("第二款呢", conversation_version=1)
        )
    )
    products = next(item for item in events if item.event == "products")
    assert [card.product_id for card in products.data.cards] == [91]
    card_display = next(
        item
        for item in events
        if item.event == "card_display_contract"
    )
    assert card_display.data.model_dump(mode="json") == {
        "mode": "single",
        "visible_product_ids": [91],
        "max_cards": 1,
        "reason": "recommendation",
    }
    assert events[-1].data.conversation_version == 2


def test_cheapest_followup_uses_snapshot_without_retrieval(
    orchestrator,
    monkeypatch,
) -> None:
    list(orchestrator.stream(_turn("500 元内敏感肌修护精华")))

    def forbidden_retrieval(*args, **kwargs):
        raise AssertionError("followup must not retrieve")

    monkeypatch.setattr(
        "app.guide.application.text_recommendation_flow.retrieve_candidates",
        forbidden_retrieval,
    )
    events = list(
        orchestrator.stream(
            _turn("哪个更便宜", conversation_version=1)
        )
    )
    products = next(item for item in events if item.event == "products")
    assert [card.product_id for card in products.data.cards] == [91]
    message = next(item for item in events if item.event == "message")
    assert "不代表综合适配更好" in message.data.content


def test_relative_price_followup_reranks_against_bound_candidate(
    real_reader,
    real_product_assets,
    conversation_state,
) -> None:
    relative_reference = ReferenceDraft(
        kind="candidate_ordinal",
        ordinal=2,
        source_span=SourceSpan(start=1, end=4),
    )
    understanding = SequenceUnderstandingPort(
        (
            StructuredUnderstanding(
                goal=UnderstandingGoal.RECOMMENDATION,
                topic=TopicCode.SKINCARE,
                observations=[],
                exact_constraints=[
                    CategoryDraft(value=TopicCode.SKINCARE),
                ],
                semantic_proposals=[],
                signal_trace=[],
                image_references=[],
                uncertainties=[],
                confidence=1.0,
            ),
            StructuredUnderstanding(
                goal=UnderstandingGoal.FOLLOWUP,
                topic=TopicCode.SKINCARE,
                observations=[],
                exact_constraints=[
                    CategoryDraft(value=TopicCode.SKINCARE),
                ],
                relative_drafts=[
                    RelativeDraft(
                        field_key="price",
                        concept_id=None,
                        direction="lower",
                        raw_text="便宜",
                        baseline=relative_reference,
                    )
                ],
                semantic_proposals=[],
                signal_trace=[],
                references=[relative_reference],
                image_references=[],
                uncertainties=[],
                confidence=1.0,
            ),
        )
    )
    flow = compose_text_recommendation_orchestrator(
        real_reader,
        product_assets=real_product_assets,
        conversation_state=conversation_state,
        understanding=understanding,
    )

    first = list(flow.stream(_turn("推荐护肤品")))
    first_cards = next(
        event for event in first if event.event == "products"
    ).data.cards
    baseline = first_cards[1]
    second = list(
        flow.stream(
            _turn("比第二款便宜", conversation_version=1)
        )
    )

    assert not any(
        event.event in {"clarify", "error"}
        for event in second
    )
    second_cards = next(
        event for event in second if event.event == "products"
    ).data.cards
    assert second_cards
    assert second_cards[0].price < baseline.price
    decision = next(
        event for event in second if event.event == "decision_process"
    )
    assert "relative=price:lower" in decision.data.evidence_refs
    relative = next(
        item
        for item in decision.data.relative_comparisons
        if item.status == "better"
    )
    assert relative.relation_kind == "numeric"
    assert set(relative.source_refs) <= set(
        decision.data.evidence_refs
    )
    message = next(
        event for event in second if event.event == "message"
    )
    assert "审核价格更低" in message.data.content


def test_missing_snapshot_clarifies_with_authoritative_version(
    orchestrator,
) -> None:
    events = list(
        orchestrator.stream(
            _turn("第二款呢", conversation_version=1)
        )
    )
    clarify = next(item for item in events if item.event == "clarify")
    assert clarify.data.question == (
        "我还没有前面那组商品，请先发起一次推荐。"
    )
    assert events[-1].data.conversation_version == 0


def test_recommendation_public_events_hide_internal_language(
    orchestrator,
) -> None:
    events = list(
        orchestrator.stream(_turn("500 元内敏感肌修护精华"))
    )
    payload = "\n".join(event.model_dump_json() for event in events)

    for term in (
        "候选",
        "代码核对",
        "硬条件",
        "证据等级",
        "放行",
        "页面记录版本",
        "本轮筛选",
    ):
        assert term not in payload


def test_followup_stream_emits_exact_card_contract_with_decision_process(
    orchestrator,
) -> None:
    list(orchestrator.stream(_turn("500 元内敏感肌修护精华")))
    events = list(
        orchestrator.stream(
            _turn("第二款呢", conversation_version=1)
        )
    )
    assert [item.event for item in events] == [
        "start",
        "stage",
        "intent",
        "decision_process",
        "answer_contract",
        "card_display_contract",
        "products",
        "presentation_contract",
        "message",
        "end",
    ]
    decision = next(
        item for item in events if item.event == "decision_process"
    )
    assert decision.data.selection_slots == []


def test_error_is_terminal_and_public(broken_orchestrator) -> None:
    events = list(
        broken_orchestrator.stream(
            _turn("500 内适合油敏肌的防晒")
        )
    )
    names = [item.event for item in events]
    assert names[-1] == "error"
    assert "end" not in names
    assert "catalog failed" not in events[-1].data.message


def test_terminal_error_does_not_write_conversation_state(
    broken_orchestrator,
    conversation_state,
) -> None:
    events = list(
        broken_orchestrator.stream(
            _turn("500 元内敏感肌修护精华")
        )
    )
    assert events[-1].event == "error"
    assert conversation_state.load("s-1") is None


def test_injected_reader_prevents_per_request_file_reload(
    real_reader,
    monkeypatch,
) -> None:
    def forbidden_reload(*args, **kwargs):
        raise AssertionError("reader must be created by application lifecycle")

    monkeypatch.setattr(
        CanonicalProductReader,
        "from_files",
        forbidden_reload,
    )
    orchestrator = compose_text_recommendation_orchestrator(
        real_reader,
        understanding=exact_echo_understanding(),
    )
    list(orchestrator.stream(_turn("防晒")))
    list(orchestrator.stream(_turn("500 内防晒")))


def test_budget_revision_reruns_full_flow_and_updates_snapshot(
    orchestrator,
    conversation_state,
    monkeypatch,
) -> None:
    list(orchestrator.stream(_turn("500 元内敏感肌修护精华")))

    from app.guide.application import text_recommendation_flow as flow

    original = flow.retrieve_candidates
    categories = []

    def recording_retrieval(*args, **kwargs):
        categories.append(kwargs["category"])
        return original(*args, **kwargs)

    monkeypatch.setattr(flow, "retrieve_candidates", recording_retrieval)
    events = list(
        orchestrator.stream(
            _turn("预算降到 100 元呢", conversation_version=1)
        )
    )

    assert [item.event for item in events] == [
        "start",
        "stage",
        "intent",
        "stage",
        "stage",
        "decision_process",
        "answer_contract",
        "card_display_contract",
        "products",
        "presentation_contract",
        "message",
        "end",
    ]
    intent = next(item for item in events if item.event == "intent")
    assert intent.data.mode == "revise"
    products = next(item for item in events if item.event == "products")
    assert [card.product_id for card in products.data.cards] == [91]
    decision = next(
        item for item in events if item.event == "decision_process"
    )
    assert decision.data.winner_status == "INSUFFICIENT_FOR_WINNER"
    assert categories == [TopicCode.SERUM]
    assert events[-1].data.conversation_version == 2

    snapshot = conversation_state.load("s-1")
    assert snapshot is not None
    assert snapshot.version == 2
    assert snapshot.query_context.category == "serum"
    assert snapshot.query_context.budget_maximum == Decimal("100")
    assert snapshot.query_context.skin == "sensitive"
    assert snapshot.query_context.efficacy == "repair"
    assert [item.product_id for item in snapshot.candidates] == [91]
    presentation = next(
        item.data
        for item in events
        if item.event == "presentation_contract"
    )
    assert presentation.mode == "revision"
    assert tuple(
        section.product_id
        for section in presentation.sections
        if section.kind == "product"
    ) == tuple(
        card.product_id for card in products.data.cards
    )


def test_recommendation_supplement_uses_revision_presentation(
    real_reader,
    real_product_assets,
    conversation_state,
) -> None:
    flow = compose_text_recommendation_orchestrator(
        real_reader,
        product_assets=real_product_assets,
        conversation_state=conversation_state,
    )
    initial = StructuredUnderstanding(
        goal=UnderstandingGoal.RECOMMENDATION,
        topic=TopicCode.SERUM,
        observations=[],
        exact_constraints=[
            CategoryDraft(value=TopicCode.SERUM),
            BudgetDraft(maximum=Decimal("400")),
        ],
        semantic_proposals=[],
        signal_trace=[],
        image_references=[],
        uncertainties=[],
        confidence=1.0,
    )
    list(
        flow.stream_understanding(
            _turn("四百以内的修护精华"),
            understanding=initial,
            route_decision=UnifiedRouteDecision(
                processor="recommendation",
                continuity="replace_task",
                focus_source="none",
            ),
            product_bindings=(),
        )
    )
    supplement = StructuredUnderstanding(
        goal=UnderstandingGoal.RECOMMENDATION,
        topic=TopicCode.SERUM,
        observations=[],
        exact_constraints=[
            CategoryDraft(value=TopicCode.SERUM),
        ],
        preference_drafts=[
            PreferenceDraft(
                field_key="texture",
                value="清爽",
            ),
        ],
        semantic_proposals=[],
        signal_trace=[],
        image_references=[],
        uncertainties=[],
        confidence=1.0,
    )

    events = list(
        flow.stream_understanding(
            _turn(
                "加上清爽偏好，不要改预算",
                conversation_version=1,
            ),
            understanding=supplement,
            route_decision=UnifiedRouteDecision(
                processor="recommendation",
                continuity="supplement",
                focus_source="none",
            ),
            product_bindings=(),
        )
    )

    presentation = next(
        event.data
        for event in events
        if event.event == "presentation_contract"
    )
    assert presentation.mode == "revision"
    snapshot = conversation_state.load("s-1")
    assert snapshot is not None
    assert snapshot.query_context is not None
    assert snapshot.query_context.budget_maximum == Decimal("400")
    assert any(
        facet.field_key == "texture" and facet.value == "清爽"
        for facet in snapshot.query_context.facets
    )


def test_stale_budget_revision_does_not_retrieve(
    orchestrator,
    monkeypatch,
) -> None:
    list(orchestrator.stream(_turn("500 元内敏感肌修护精华")))

    def forbidden_retrieval(*args, **kwargs):
        raise AssertionError("stale revision must not retrieve")

    monkeypatch.setattr(
        "app.guide.application.text_recommendation_flow.retrieve_candidates",
        forbidden_retrieval,
    )
    events = list(
        orchestrator.stream(
            _turn("预算降到100元呢", conversation_version=0)
        )
    )

    assert "products" not in [item.event for item in events]
    clarify = next(item for item in events if item.event == "clarify")
    assert "状态已变化" in clarify.data.question
    assert events[-1].data.conversation_version == 1


def test_no_candidate_budget_revision_retains_previous_snapshot(
    orchestrator,
    conversation_state,
) -> None:
    list(orchestrator.stream(_turn("500 元内敏感肌修护精华")))
    before = conversation_state.load("s-1")

    events = list(
        orchestrator.stream(
            _turn("预算降到50元呢", conversation_version=1)
        )
    )

    products = next(item for item in events if item.event == "products")
    assert products.data.cards == []
    card_display = next(
        item
        for item in events
        if item.event == "card_display_contract"
    )
    assert card_display.data.model_dump(mode="json") == {
        "mode": "none",
        "visible_product_ids": [],
        "max_cards": 0,
        "reason": None,
    }
    message = next(item for item in events if item.event == "message")
    assert "前面已经挑出的商品先保留" in message.data.content
    assert events[-1].data.conversation_version == 1
    assert conversation_state.load("s-1") == before


def test_revision_error_is_terminal_and_keeps_previous_snapshot(
    orchestrator,
    conversation_state,
    monkeypatch,
) -> None:
    list(orchestrator.stream(_turn("500 元内敏感肌修护精华")))
    before = conversation_state.load("s-1")

    def broken_retrieval(*args, **kwargs):
        raise RuntimeError("revision retrieval failed")

    monkeypatch.setattr(
        "app.guide.application.text_recommendation_flow.retrieve_candidates",
        broken_retrieval,
    )
    events = list(
        orchestrator.stream(
            _turn("预算降到100元呢", conversation_version=1)
        )
    )

    assert events[-1].event == "error"
    assert "end" not in [item.event for item in events]
    assert conversation_state.load("s-1") == before


def test_revision_presentation_error_does_not_update_snapshot(
    orchestrator,
    conversation_state,
    monkeypatch,
) -> None:
    list(orchestrator.stream(_turn("500 元内敏感肌修护精华")))
    before = conversation_state.load("s-1")

    def broken_message(*args, **kwargs):
        raise RuntimeError("revision presentation failed")

    monkeypatch.setattr(
        (
            "app.guide.application.text_recommendation_flow."
            "build_budget_revision_message"
        ),
        broken_message,
    )
    events = list(
        orchestrator.stream(
            _turn("预算降到100元呢", conversation_version=1)
        )
    )

    assert events[-1].event == "error"
    assert "end" not in [item.event for item in events]
    assert conversation_state.load("s-1") == before


def test_budget_revision_cas_conflict_keeps_authoritative_snapshot(
    orchestrator,
    conversation_state,
    monkeypatch,
) -> None:
    list(orchestrator.stream(_turn("500 元内敏感肌修护精华")))
    before = conversation_state.load("s-1")

    def conflicting_save(snapshot, *, expected_version):
        raise ConversationStateConflict(snapshot.session_id)

    monkeypatch.setattr(
        conversation_state,
        "save",
        conflicting_save,
    )
    events = list(
        orchestrator.stream(
            _turn("预算降到100元呢", conversation_version=1)
        )
    )

    names = [item.event for item in events]
    assert names == ["start", "intent", "clarify", "end"]
    clarify = next(item for item in events if item.event == "clarify")
    assert "状态已变化" in clarify.data.question
    assert events[-1].data.conversation_version == 1
    assert conversation_state.load("s-1") == before


def test_followup_cas_conflict_does_not_publish_products_or_message(
    orchestrator,
    conversation_state,
    monkeypatch,
) -> None:
    list(orchestrator.stream(_turn("500 元内敏感肌修护精华")))
    before = conversation_state.load("s-1")
    assert before is not None

    def conflicting_save(snapshot, *, expected_version):
        raise ConversationStateConflict(snapshot.session_id)

    monkeypatch.setattr(
        conversation_state,
        "save",
        conflicting_save,
    )
    events = list(
        orchestrator.stream(
            _turn("第二款呢", conversation_version=1)
        )
    )

    assert [item.event for item in events] == [
        "start",
        "intent",
        "clarify",
        "end",
    ]
    assert events[-1].data.conversation_version == 1
    assert conversation_state.load("s-1") == before


def test_budget_revision_changes_latest_candidate_boundary(
    orchestrator,
) -> None:
    list(orchestrator.stream(_turn("500 元内敏感肌修护精华")))
    list(
        orchestrator.stream(
            _turn("预算降到100元呢", conversation_version=1)
        )
    )
    events = list(
        orchestrator.stream(
            _turn("第二款呢", conversation_version=2)
        )
    )

    assert [item.event for item in events] == [
        "start",
        "intent",
        "clarify",
        "end",
    ]
    intent = next(item for item in events if item.event == "intent")
    assert intent.data.mode == "clarify"
    clarify = next(item for item in events if item.event == "clarify")
    assert "只展示了 1 款" in clarify.data.question
    assert events[-1].data.conversation_version == 2


def test_explicit_category_query_wins_over_budget_revision(
    orchestrator,
    conversation_state,
) -> None:
    list(orchestrator.stream(_turn("500 元内敏感肌修护精华")))
    events = list(
        orchestrator.stream(
            _turn("100 元内防晒", conversation_version=1)
        )
    )

    intent = next(item for item in events if item.event == "intent")
    products = next(item for item in events if item.event == "products")
    assert intent.data.mode == "recommend"
    assert [card.product_id for card in products.data.cards] == [51, 54, 57]
    assert events[-1].data.conversation_version == 2
    snapshot = conversation_state.load("s-1")
    assert snapshot is not None
    assert snapshot.query_context.category == "sunscreen"
    assert snapshot.query_context.budget_maximum == Decimal("100")


def test_bare_amount_does_not_inherit_query_context(
    orchestrator,
    conversation_state,
) -> None:
    list(orchestrator.stream(_turn("500 元内敏感肌修护精华")))
    before = conversation_state.load("s-1")
    events = list(
        orchestrator.stream(
            _turn("100元呢", conversation_version=1)
        )
    )

    assert "products" not in [item.event for item in events]
    clarify = next(item for item in events if item.event == "clarify")
    assert "品类" in clarify.data.question
    assert events[-1].data.conversation_version == 1
    assert conversation_state.load("s-1") == before


def test_skin_revision_reruns_full_flow_and_updates_snapshot(
    orchestrator,
    conversation_state,
    monkeypatch,
) -> None:
    first = list(
        orchestrator.stream(_turn("500 元内修护精华"))
    )
    first_products = next(
        item for item in first if item.event == "products"
    )
    first_decision = next(
        item for item in first if item.event == "decision_process"
    )
    assert [card.product_id for card in first_products.data.cards] == [
        38,
        91,
    ]
    assert first_decision.data.winner_status == "SELECTED"
    assert first[-1].data.conversation_version == 1

    from app.guide.application import text_recommendation_flow as flow

    original = flow.retrieve_candidates
    categories = []

    def recording_retrieval(*args, **kwargs):
        categories.append(kwargs["category"])
        return original(*args, **kwargs)

    monkeypatch.setattr(flow, "retrieve_candidates", recording_retrieval)
    events = list(
        orchestrator.stream(
            _turn("改成敏感肌呢", conversation_version=1)
        )
    )

    assert [item.event for item in events] == [
        "start",
        "stage",
        "intent",
        "stage",
        "stage",
        "decision_process",
        "answer_contract",
        "card_display_contract",
        "products",
        "presentation_contract",
        "message",
        "end",
    ]
    intent = next(item for item in events if item.event == "intent")
    assert intent.data.mode == "revise"
    products = next(item for item in events if item.event == "products")
    assert [card.product_id for card in products.data.cards] == [38, 91]
    decision = next(
        item for item in events if item.event == "decision_process"
    )
    assert decision.data.winner_status == "INSUFFICIENT_FOR_WINNER"
    message = next(item for item in events if item.event == "message")
    assert "肤质调整为“敏感肌”" in message.data.content
    assert "预算上限调整" not in message.data.content
    assert categories == [TopicCode.SERUM]
    assert events[-1].data.conversation_version == 2

    snapshot = conversation_state.load("s-1")
    assert snapshot is not None
    assert snapshot.version == 2
    assert snapshot.query_context.category == "serum"
    assert snapshot.query_context.budget_maximum == Decimal("500")
    assert snapshot.query_context.skin == "sensitive"
    assert snapshot.query_context.efficacy == "repair"
    assert [item.product_id for item in snapshot.candidates] == [38, 91]


def test_missing_snapshot_skin_revision_does_not_retrieve(
    orchestrator,
    conversation_state,
    monkeypatch,
) -> None:
    def forbidden_retrieval(*args, **kwargs):
        raise AssertionError("missing snapshot must not retrieve")

    monkeypatch.setattr(
        "app.guide.application.text_recommendation_flow.retrieve_candidates",
        forbidden_retrieval,
    )
    events = list(
        orchestrator.stream(
            _turn("改成敏感肌呢", conversation_version=1)
        )
    )

    assert [item.event for item in events] == [
        "start",
        "intent",
        "clarify",
        "end",
    ]
    clarify = next(item for item in events if item.event == "clarify")
    assert "完整推荐" in clarify.data.question
    assert events[-1].data.conversation_version == 0
    assert conversation_state.load("s-1") is None


def test_stale_skin_revision_does_not_retrieve_or_update_snapshot(
    orchestrator,
    conversation_state,
    monkeypatch,
) -> None:
    list(orchestrator.stream(_turn("500 元内修护精华")))
    before = conversation_state.load("s-1")

    def forbidden_retrieval(*args, **kwargs):
        raise AssertionError("stale skin revision must not retrieve")

    monkeypatch.setattr(
        "app.guide.application.text_recommendation_flow.retrieve_candidates",
        forbidden_retrieval,
    )
    events = list(
        orchestrator.stream(
            _turn("改成敏感肌呢", conversation_version=0)
        )
    )

    assert "products" not in [item.event for item in events]
    clarify = next(item for item in events if item.event == "clarify")
    assert "状态已变化" in clarify.data.question
    assert events[-1].data.conversation_version == 1
    assert conversation_state.load("s-1") == before


def test_ambiguous_skin_revision_clarifies_without_state_change(
    orchestrator,
    conversation_state,
    monkeypatch,
) -> None:
    list(orchestrator.stream(_turn("500 元内修护精华")))
    before = conversation_state.load("s-1")

    def forbidden_retrieval(*args, **kwargs):
        raise AssertionError("ambiguous skin revision must not retrieve")

    monkeypatch.setattr(
        "app.guide.application.text_recommendation_flow.retrieve_candidates",
        forbidden_retrieval,
    )
    events = list(
        orchestrator.stream(
            _turn("换个肤质", conversation_version=1)
        )
    )

    assert [item.event for item in events] == [
        "start",
        "stage",
        "intent",
        "clarify",
        "end",
    ]
    clarify = next(item for item in events if item.event == "clarify")
    assert "需要你确认" in clarify.data.question
    assert events[-1].data.conversation_version == 1
    assert conversation_state.load("s-1") == before


def test_compound_budget_and_skin_revision_is_not_taken_by_budget_branch(
    orchestrator,
    conversation_state,
    monkeypatch,
) -> None:
    list(orchestrator.stream(_turn("500 元内修护精华")))
    before = conversation_state.load("s-1")

    def forbidden_retrieval(*args, **kwargs):
        raise AssertionError("compound revision must not retrieve")

    monkeypatch.setattr(
        "app.guide.application.text_recommendation_flow.retrieve_candidates",
        forbidden_retrieval,
    )
    events = list(
        orchestrator.stream(
            _turn(
                "预算改成300元，肤质改成敏感肌",
                conversation_version=1,
            )
        )
    )

    assert [item.event for item in events] == [
        "start",
        "stage",
        "intent",
        "clarify",
        "end",
    ]
    intent = next(item for item in events if item.event == "intent")
    assert intent.data.mode == "clarify"
    clarify = next(item for item in events if item.event == "clarify")
    assert "需要你确认" in clarify.data.question
    assert events[-1].data.conversation_version == 1
    assert conversation_state.load("s-1") == before


def test_no_candidate_skin_revision_retains_previous_snapshot(
    orchestrator,
    conversation_state,
    monkeypatch,
) -> None:
    list(orchestrator.stream(_turn("500 元内修护精华")))
    before = conversation_state.load("s-1")

    def empty_retrieval(*args, **kwargs):
        return RetrievalResult(
            candidates=[],
            knowledge_evidence=[],
            review_evidence=[],
            memory_evidence=[],
            missing_sources=[],
        )

    monkeypatch.setattr(
        "app.guide.application.text_recommendation_flow.retrieve_candidates",
        empty_retrieval,
    )
    events = list(
        orchestrator.stream(
            _turn("改成敏感肌呢", conversation_version=1)
        )
    )

    products = next(item for item in events if item.event == "products")
    assert products.data.cards == []
    message = next(item for item in events if item.event == "message")
    assert "前面已经挑出的商品先保留" in message.data.content
    assert events[-1].data.conversation_version == 1
    assert conversation_state.load("s-1") == before


def test_skin_revision_presentation_error_keeps_previous_snapshot(
    orchestrator,
    conversation_state,
    monkeypatch,
) -> None:
    list(orchestrator.stream(_turn("500 元内修护精华")))
    before = conversation_state.load("s-1")

    def broken_message(*args, **kwargs):
        raise RuntimeError("skin revision presentation failed")

    monkeypatch.setattr(
        (
            "app.guide.application.text_recommendation_flow."
            "build_skin_revision_message"
        ),
        broken_message,
    )
    events = list(
        orchestrator.stream(
            _turn("改成敏感肌呢", conversation_version=1)
        )
    )

    assert events[-1].event == "error"
    assert "end" not in [item.event for item in events]
    assert conversation_state.load("s-1") == before


def test_skin_revision_cas_conflict_keeps_authoritative_snapshot(
    orchestrator,
    conversation_state,
    monkeypatch,
) -> None:
    list(orchestrator.stream(_turn("500 元内修护精华")))
    before = conversation_state.load("s-1")

    def conflicting_save(snapshot, *, expected_version):
        raise ConversationStateConflict(snapshot.session_id)

    monkeypatch.setattr(
        conversation_state,
        "save",
        conflicting_save,
    )
    events = list(
        orchestrator.stream(
            _turn("改成敏感肌呢", conversation_version=1)
        )
    )

    assert [item.event for item in events] == [
        "start",
        "intent",
        "clarify",
        "end",
    ]
    clarify = next(item for item in events if item.event == "clarify")
    assert "状态已变化" in clarify.data.question
    assert events[-1].data.conversation_version == 1
    assert conversation_state.load("s-1") == before


def test_followup_after_skin_revision_uses_new_snapshot_without_retrieval(
    orchestrator,
    conversation_state,
    monkeypatch,
) -> None:
    list(orchestrator.stream(_turn("500 元内修护精华")))
    list(
        orchestrator.stream(
            _turn("改成敏感肌呢", conversation_version=1)
        )
    )

    def forbidden_retrieval(*args, **kwargs):
        raise AssertionError("followup must use revised snapshot")

    monkeypatch.setattr(
        "app.guide.application.text_recommendation_flow.retrieve_candidates",
        forbidden_retrieval,
    )
    events = list(
        orchestrator.stream(
            _turn("第二款呢", conversation_version=2)
        )
    )

    products = next(item for item in events if item.event == "products")
    assert [card.product_id for card in products.data.cards] == [91]
    assert events[-1].data.conversation_version == 3
    snapshot = conversation_state.load("s-1")
    assert snapshot is not None
    assert snapshot.version == 3
    assert snapshot.query_context.skin == "sensitive"
    assert [item.product_id for item in snapshot.candidates] == [38, 91]
