import os
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import sys
import tempfile
from typing import Any, Callable, Mapping

from app.guide.adapters.catalog import (
    CanonicalIdentityCatalog,
    CanonicalProductReader,
)
from app.guide.adapters.catalog.canonical_guide_catalog import (
    CanonicalGuideCatalog,
)
from app.guide.adapters.catalog.seed_product_assets import (
    SeedProductAsset,
    load_seed_product_assets,
)
from app.guide.adapters.state import (
    InMemoryConversationState,
    InMemorySessionLocks,
    RegisteredFeedbackConversationReferenceResolver,
    SqliteConversationState,
    SqliteFeedbackTargetRegistry,
    SqliteImageBundleState,
    SqliteProfileState,
    SqliteProfileFeedbackReferenceResolver,
)
from app.guide.application.consultation_chat_flow import (
    ConsultationChatFlow,
)
from app.guide.application.consultation_coordinator import (
    ConsultationApplicationCoordinator,
)
from app.guide.application.chat_api_adapter import (
    PublicEventCommitConversationState,
)
from app.guide.application.image_bundle_service import ImageBundleService
from app.guide.application.text_recommendation_flow import (
    TextRecommendationOrchestrator,
)
from app.guide.application.unified_guide_flow import (
    UnifiedGuideFlow,
    UnifiedUnderstandingAdapter,
)
from app.guide.feedback.delivery import TrustedFeedbackService
from app.guide.feedback.event_recorder import FeedbackEventRecorder
from app.guide.feedback.ports import (
    ConversationStatePort,
    SessionLockPort,
    Slice1DisabledFeedback,
)
from app.guide.feedback.profile_contracts import ProfileOwnerRef
from app.guide.feedback.profile_policy import ResolvedProfileContext
from app.guide.presentation.presentation_compiler import (
    PresentationCompiler,
)
from app.guide.adapters.state.sqlite_feedback_event_store import (
    SqliteFeedbackEventStore,
)
from app.guide.retrieval.approved_review_assets import (
    load_approved_review_assets,
)
from app.guide.retrieval.category_fact_assets import (
    load_category_fact_assets,
)
from app.guide.retrieval.category_fact_contracts import (
    category_field_registry,
)
from app.guide.retrieval.category_fact_reader import CategoryFactReader
from app.guide.retrieval.controlled_product_aliases import (
    ControlledProductAliasRegistry,
    load_controlled_product_aliases,
)
from app.guide.retrieval.general_knowledge_assets import (
    GeneralKnowledgeAssets,
    load_general_knowledge_assets,
)
from app.guide.retrieval.general_knowledge_retrieval import (
    GeneralKnowledgeRetriever,
)
from app.guide.retrieval.merchant_claim_assets import (
    load_merchant_claim_assets,
)
from app.guide.retrieval.merchant_claim_reader import (
    ClaimAugmentedCategoryFactReader,
    MerchantClaimReader,
)
from app.guide.retrieval.product_display_assets import (
    ProductDisplayBindingReader,
    load_product_display_assets,
)
from app.guide.retrieval.product_evidence_retrieval import (
    ProductEvidenceRetriever,
)
from app.guide.retrieval.product_evidence_assets import (
    load_product_evidence_assets,
)
from app.guide.retrieval.product_evidence_reader import ProductEvidenceReader
from app.guide.retrieval.ports import CategoryFactPort
from app.guide.retrieval.product_name_resolver import ProductNameResolver
from app.guide.retrieval.review_reader import ReviewEvidenceReader
from app.guide.retrieval.selection_fact_reader import SelectionFactReader
from app.guide.retrieval.selection_parent_concept_assets import (
    SelectionConceptAssets,
    load_selection_concept_assets,
)
from app.guide.retrieval.selection_parent_concept_reader import (
    SelectionParentConceptReader,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
GUIDE_STATE_DIR_ENV = "XIAORO_GUIDE_STATE_DIR"
GUIDE_IMAGE_WEIGHT_PATH_ENV = "XIAORO_GUIDE_IMAGE_WEIGHT_PATH"
GUIDE_IMAGE_DEVICE_ENV = "XIAORO_GUIDE_IMAGE_DEVICE"
GUIDE_IMAGE_ARTIFACT_RELATIVE_PATH = (
    Path("data")
    / "guide_image_index"
    / "openclip_vit_b32_laion2b_s34b_b79k_v1"
)
GUIDE_IMAGE_MANIFEST_SHA256 = (
    "f47e183aaec1f8418f9d4dcef78481607ab4a74d38b46920025c23070a3427d9"
)
GUIDE_IMAGE_INDEX_SHA256 = (
    "f61ba8ed45dc6f3d285e22016f7c643bfd01eec78ba65c84e75e5fabb843d340"
)
GUIDE_IMAGE_MODEL_NAME = (
    "OpenCLIP:ViT-B-32:laion2b_s34b_b79k@"
    "1a25a446712ba5ee05982a381eed697ef9b435cf"
)
GUIDE_IMAGE_WEIGHT_SHA256 = (
    "ac4f8c4b88af6d963118cbf40ad93176d092abbedfcb752601ae1866352656e6"
)
GUIDE_IMAGE_PREPROCESSING_VERSION = (
    "openclip-3.3.0|ViT-B-32|laion2b_s34b_b79k@"
    "1a25a446712ba5ee05982a381eed697ef9b435cf|rgb|"
    "resize-shortest-224-bicubic-antialias|center-crop-224|"
    "mean-0.48145466,0.4578275,0.40821073|"
    "std-0.26862954,0.26130258,0.27577711|tensor-fp32"
)
GUIDE_IMAGE_VECTOR_DIMENSION = 512
GUIDE_REVIEW_SOURCE_RELATIVE_PATH = (
    Path("data") / "guide_review_sources"
)
GUIDE_REVIEW_MANIFEST_SHA256 = (
    "823c249166e93b4ab709b3423fa8a97a23e3ab3e7677e5d39d74abc21c165113"
)
GUIDE_CATEGORY_FACT_RELATIVE_PATH = (
    Path("data")
    / "guide_category_facts"
    / "category_facts_v1_manifest.json"
)
GUIDE_CATEGORY_FACT_MANIFEST_SHA256 = (
    "56e10e7dc066910b3d1f1aba65c4002b030a918172601c1ba643376457e7f438"
)
GUIDE_PRODUCT_DISPLAY_RELATIVE_PATH = (
    Path("data")
    / "guide_product_display_bindings"
    / "v1"
    / "product_display_bindings_v1_manifest.json"
)
GUIDE_PRODUCT_DISPLAY_MANIFEST_SHA256 = (
    "1453be0d77db36914ad64901ab94ffb8fc269df3cd1fc4911912cfe5476631c2"
)
GUIDE_MERCHANT_CLAIM_RELATIVE_PATH = (
    Path("data")
    / "guide_merchant_claims"
    / "merchant_claims_v1_manifest.json"
)
GUIDE_MERCHANT_CLAIM_ASSET_RELATIVE_PATH = (
    Path("data")
    / "guide_merchant_claims"
    / (
        "merchant_claims_v1."
        "8b90f33d45368c269076d96a8b0ca76fd1c5fcac988fd96cc93937da7d4207fd"
        ".jsonl"
    )
)
GUIDE_MERCHANT_CLAIM_MANIFEST_SHA256 = (
    "d906c0a6d42636c89d1ccb408413c786b817cbb2ddf44678143c427228a21e75"
)
GUIDE_PRODUCT_EVIDENCE_RELATIVE_PATH = (
    Path("data")
    / "guide_product_evidence"
    / "product_evidence_v1_manifest.json"
)
GUIDE_PRODUCT_EVIDENCE_ASSET_RELATIVE_PATH = (
    Path("data")
    / "guide_product_evidence"
    / (
        "product_evidence_v1."
        "52d236ad446309907368f21d74fa343132436ac509154bd7b035c6ce48178f81"
        ".jsonl"
    )
)
GUIDE_PRODUCT_EVIDENCE_AUDIT_RELATIVE_PATH = (
    Path("data")
    / "guide_product_evidence"
    / (
        "image_audit_v1."
        "1ded80381a5b225b53826fbde6958d8f9b94f216414ca66be135e522ba498200"
        ".jsonl"
    )
)
GUIDE_PRODUCT_EVIDENCE_MANIFEST_SHA256 = (
    "ca5cee9dc0e70e64f3e30b2faf7aed35d45fae45272a299c540bfb79d071b351"
)
GUIDE_GENERAL_KNOWLEDGE_RELATIVE_PATH = (
    Path("data")
    / "guide_general_knowledge"
    / "general_knowledge_v1_manifest.json"
)
GUIDE_GENERAL_KNOWLEDGE_MANIFEST_SHA256 = (
    "09bea87c4c56f18b982f474a42ef1ca0abd758da8b90a73a34681ec7c605ac21"
)
GUIDE_SELECTION_CONCEPT_RELATIVE_PATH = (
    Path("data")
    / "guide_selection_concepts"
    / "v2"
    / "selection_concepts_v1_manifest.json"
)
GUIDE_SELECTION_CONCEPT_INVENTORY_RELATIVE_PATH = (
    Path("docs")
    / "audits"
    / "selection-concepts"
    / "review-v2"
    / "inventory.json"
)
GUIDE_SELECTION_CONCEPT_REVIEW_RELATIVE_PATH = (
    Path("docs")
    / "audits"
    / "selection-concepts"
    / "review-v2"
    / "reviews.jsonl"
)
GUIDE_SELECTION_CONCEPT_MANIFEST_SHA256 = (
    "2783fb241c5f3be60bcb70425e67b20df65bb03af82bd2b62c3d75875a7e2f95"
)
GUIDE_CONTROLLED_ALIAS_MANIFEST_RELATIVE_PATH = (
    Path("data")
    / "canonical"
    / "controlled_product_aliases_v1_manifest.json"
)
GUIDE_CONTROLLED_ALIAS_ASSET_RELATIVE_PATH = (
    Path("data")
    / "canonical"
    / "controlled_product_aliases_v1.jsonl"
)


@dataclass(frozen=True, slots=True)
class ConsultationVerticalRuntime:
    consultation: ConsultationChatFlow
    recommendation: TextRecommendationOrchestrator
    unified: UnifiedGuideFlow
    presentation_compiler: PresentationCompiler
    conversation_state: SqliteConversationState
    profile_state: SqliteProfileState
    profile_resolver: Callable[..., ResolvedProfileContext]
    session_locks: SessionLockPort

    @staticmethod
    def profile_owner(session_id: str) -> ProfileOwnerRef:
        if not isinstance(session_id, str) or not session_id:
            raise ValueError("session_id must be a non-empty string")
        digest = sha256(
            f"xiaoro-consultation-profile-v1\0{session_id}".encode(
                "utf-8"
            )
        ).hexdigest()
        return ProfileOwnerRef(
            scope="anonymous_browser",
            subject_id=f"profile_{digest}",
        )


def guide_state_directory() -> Path:
    if GUIDE_STATE_DIR_ENV in os.environ:
        return _require_absolute_state_directory(
            os.environ[GUIDE_STATE_DIR_ENV],
            source=GUIDE_STATE_DIR_ENV,
        )
    return _require_absolute_state_directory(
        Path(tempfile.gettempdir())
        / f"xiaoro-guide-state-{os.getuid()}",
        source="default guide state directory",
    )


def _require_absolute_state_directory(
    configured: str | os.PathLike[str],
    *,
    source: str,
) -> Path:
    state_root = Path(configured).expanduser()
    if not os.fspath(configured) or not state_root.is_absolute():
        raise ValueError(
            f"{source} must be a non-empty absolute path"
        )
    return state_root


def _runtime_state_directory(
    state_dir: str | os.PathLike[str] | None,
) -> Path:
    if state_dir is None:
        return guide_state_directory()
    return _require_absolute_state_directory(
        state_dir,
        source="state_dir",
    )


def image_bundle_database_path() -> Path:
    return guide_state_directory() / "image_bundles.sqlite3"


def conversation_database_path() -> Path:
    return guide_state_directory() / "conversations.sqlite3"


def build_image_bundle_service(
    *,
    database_path: str | os.PathLike[str] | None = None,
) -> ImageBundleService:
    return ImageBundleService(
        state=SqliteImageBundleState(
            database_path or image_bundle_database_path()
        ),
    )


def build_feedback_service(
    *,
    state_directory: str | os.PathLike[str] | None = None,
) -> TrustedFeedbackService:
    state_root = Path(
        state_directory or guide_state_directory()
    ).expanduser().absolute()
    targets = SqliteFeedbackTargetRegistry(
        state_root / "feedback_targets.sqlite3",
        trusted_state_root=state_root,
    )
    profiles = SqliteProfileState(
        state_root / "profiles.sqlite3",
        trusted_state_root=state_root,
    )
    recorder = FeedbackEventRecorder(
        store=SqliteFeedbackEventStore(
            state_root / "feedback_events.sqlite3"
        ),
        conversation_references=(
            RegisteredFeedbackConversationReferenceResolver(targets)
        ),
        profile_references=(
            SqliteProfileFeedbackReferenceResolver(profiles)
        ),
    )
    return TrustedFeedbackService(
        targets=targets,
        profiles=profiles,
        recorder=recorder,
    )


def build_review_evidence_reader(
    repo_root: Path = REPO_ROOT,
) -> ReviewEvidenceReader:
    source_root = repo_root / GUIDE_REVIEW_SOURCE_RELATIVE_PATH
    assets = load_approved_review_assets(
        manifest_path=(
            source_root
            / "approved_tmall_feed_reviews_v1_manifest.json"
        ),
        sources_path=(
            source_root / "approved_tmall_feed_reviews_v1.jsonl"
        ),
        expected_manifest_sha256=GUIDE_REVIEW_MANIFEST_SHA256,
    )
    return ReviewEvidenceReader(
        catalog=assets.catalog,
        evidence=assets.evidence,
    )


def build_category_fact_reader(
    reader: CanonicalProductReader,
    *,
    repo_root: Path = REPO_ROOT,
) -> ClaimAugmentedCategoryFactReader:
    registry = category_field_registry()
    assets = load_category_fact_assets(
        manifest_path=repo_root / GUIDE_CATEGORY_FACT_RELATIVE_PATH,
        canonical_reader=reader,
        field_registry=registry,
        expected_manifest_sha256=(
            GUIDE_CATEGORY_FACT_MANIFEST_SHA256
        ),
    )
    base = CategoryFactReader(
        assets=assets,
        field_registry=registry,
    )
    merchant_assets = load_merchant_claim_assets(
        manifest_path=repo_root / GUIDE_MERCHANT_CLAIM_RELATIVE_PATH,
        claims_path=repo_root / GUIDE_MERCHANT_CLAIM_ASSET_RELATIVE_PATH,
        expected_manifest_sha256=(
            GUIDE_MERCHANT_CLAIM_MANIFEST_SHA256
        ),
    )
    return ClaimAugmentedCategoryFactReader(
        base=base,
        claims=MerchantClaimReader(merchant_assets),
        field_registry=registry,
    )


def build_product_display_binding_reader(
    repo_root: Path = REPO_ROOT,
) -> ProductDisplayBindingReader:
    return ProductDisplayBindingReader(
        load_product_display_assets(
            manifest_path=(
                repo_root / GUIDE_PRODUCT_DISPLAY_RELATIVE_PATH
            ),
            expected_manifest_sha256=(
                GUIDE_PRODUCT_DISPLAY_MANIFEST_SHA256
            ),
        )
    )


def build_product_evidence_reader(
    repo_root: Path = REPO_ROOT,
) -> ProductEvidenceReader:
    assets = load_product_evidence_assets(
        manifest_path=repo_root / GUIDE_PRODUCT_EVIDENCE_RELATIVE_PATH,
        evidence_path=(
            repo_root / GUIDE_PRODUCT_EVIDENCE_ASSET_RELATIVE_PATH
        ),
        audit_path=(
            repo_root / GUIDE_PRODUCT_EVIDENCE_AUDIT_RELATIVE_PATH
        ),
        expected_manifest_sha256=(
            GUIDE_PRODUCT_EVIDENCE_MANIFEST_SHA256
        ),
    )
    return ProductEvidenceReader(assets)


def build_general_knowledge_assets(
    repo_root: Path = REPO_ROOT,
) -> GeneralKnowledgeAssets:
    return load_general_knowledge_assets(
        repo_root / GUIDE_GENERAL_KNOWLEDGE_RELATIVE_PATH,
        expected_manifest_sha256=(
            GUIDE_GENERAL_KNOWLEDGE_MANIFEST_SHA256
        ),
        repo_root=repo_root,
    )


def build_selection_concept_assets(
    repo_root: Path = REPO_ROOT,
) -> SelectionConceptAssets:
    return load_selection_concept_assets(
        repo_root / GUIDE_SELECTION_CONCEPT_RELATIVE_PATH,
        expected_manifest_sha256=(
            GUIDE_SELECTION_CONCEPT_MANIFEST_SHA256
        ),
        inventory_path=(
            repo_root
            / GUIDE_SELECTION_CONCEPT_INVENTORY_RELATIVE_PATH
        ),
        review_path=(
            repo_root / GUIDE_SELECTION_CONCEPT_REVIEW_RELATIVE_PATH
        ),
    )


def build_selection_parent_concept_reader(
    repo_root: Path = REPO_ROOT,
) -> SelectionParentConceptReader:
    return SelectionParentConceptReader(
        build_selection_concept_assets(repo_root).projections
    )


def build_controlled_product_alias_registry(
    reader: CanonicalProductReader,
    *,
    repo_root: Path = REPO_ROOT,
) -> ControlledProductAliasRegistry:
    canonical_manifest_path = (
        repo_root / "data" / "canonical" / "core_products_v1_manifest.json"
    )
    try:
        canonical_manifest = json.loads(
            canonical_manifest_path.read_text(encoding="utf-8")
        )
        canonical_sha256 = canonical_manifest["products_sha256"]
    except (
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        KeyError,
        TypeError,
    ) as exc:
        raise ValueError(
            "controlled aliases require the Canonical product manifest"
        ) from exc
    if not isinstance(canonical_sha256, str):
        raise ValueError(
            "Canonical products_sha256 must be a string"
        )
    return load_controlled_product_aliases(
        manifest_path=(
            repo_root / GUIDE_CONTROLLED_ALIAS_MANIFEST_RELATIVE_PATH
        ),
        aliases_path=(
            repo_root / GUIDE_CONTROLLED_ALIAS_ASSET_RELATIVE_PATH
        ),
        catalog=CanonicalIdentityCatalog(reader),
        canonical_sha256=canonical_sha256,
    )


def build_product_evidence_retriever(
    repo_root: Path = REPO_ROOT,
    *,
    reader: ProductEvidenceReader | None = None,
) -> ProductEvidenceRetriever:
    return ProductEvidenceRetriever(
        reader or build_product_evidence_reader(repo_root)
    )


def build_selection_fact_reader(
    *,
    category_facts: ClaimAugmentedCategoryFactReader,
    product_evidence: ProductEvidenceReader,
) -> SelectionFactReader:
    return SelectionFactReader(
        base=category_facts.base,
        claims=category_facts.claims,
        evidence=product_evidence,
    )


def compose_text_recommendation_orchestrator(
    reader: CanonicalProductReader,
    *,
    product_assets: Mapping[int, SeedProductAsset] | None = None,
    conversation_state: ConversationStatePort | None = None,
    session_locks: SessionLockPort | None = None,
    profile_resolver=None,
    review_evidence: ReviewEvidenceReader | None = None,
    category_fact_port: CategoryFactPort | None = None,
    merchant_claims: MerchantClaimReader | None = None,
    product_evidence: ProductEvidenceRetriever | None = None,
    general_knowledge: GeneralKnowledgeRetriever | None = None,
    selection_facts: SelectionFactReader | None = None,
    concept_reader: SelectionParentConceptReader | None = None,
    product_display_bindings: (
        ProductDisplayBindingReader | None
    ) = None,
    controlled_product_aliases: (
        ControlledProductAliasRegistry | None
    ) = None,
    understanding=None,
    presentation_copywriter=None,
) -> TextRecommendationOrchestrator:
    catalog = CanonicalGuideCatalog(
        reader,
        product_assets=product_assets,
        category_fact_port=category_fact_port,
        selection_fact_port=selection_facts,
        product_display_bindings=product_display_bindings,
    )
    active_conversation_state = (
        conversation_state or InMemoryConversationState()
    )
    if not isinstance(
        active_conversation_state,
        PublicEventCommitConversationState,
    ):
        active_conversation_state = PublicEventCommitConversationState(
            active_conversation_state
        )
    return TextRecommendationOrchestrator(
        category_catalog=catalog,
        scenario_evidence=catalog,
        decision_facts=catalog,
        presentation_facts=catalog,
        review_evidence=(
            review_evidence or build_review_evidence_reader()
        ),
        merchant_claims=(
            merchant_claims
            if merchant_claims is not None
            else (
                category_fact_port.claims
                if isinstance(
                    category_fact_port,
                    ClaimAugmentedCategoryFactReader,
                )
                else None
            )
        ),
        product_evidence=product_evidence,
        general_knowledge=general_knowledge,
        concept_reader=concept_reader,
        feedback=Slice1DisabledFeedback(),
        conversation_state=active_conversation_state,
        session_locks=session_locks or InMemorySessionLocks(),
        understanding=understanding,
        product_name_resolver=ProductNameResolver(
            CanonicalIdentityCatalog(reader),
            controlled_aliases=controlled_product_aliases,
        ),
        presentation_compiler=PresentationCompiler(
            copywriter=presentation_copywriter
        ),
        profile_resolver=profile_resolver,
    )


def build_presentation_copywriter():
    from app.guide.adapters.llm.deepseek_intent import (
        DEEPSEEK_OFFICIAL_BASE_URL,
    )
    from app.guide.adapters.llm.deepseek_presentation_copywriter import (
        DeepSeekPresentationCopywriterAdapter,
    )
    from app.guide.adapters.llm.siliconflow_presentation_copywriter import (
        SiliconFlowPresentationCopywriterAdapter,
    )
    from app.guide_runtime.copywriter_config import CopywriterLlmConfig

    config = CopywriterLlmConfig.from_environment()
    if not config.is_ready:
        return None
    ready = config.require_ready()
    if ready.base_url == DEEPSEEK_OFFICIAL_BASE_URL:
        assert ready.api_key is not None
        assert ready.model is not None
        return DeepSeekPresentationCopywriterAdapter(
            api_key=ready.api_key,
            model=ready.model,
            timeout_seconds=ready.timeout_seconds,
            max_tokens=ready.max_tokens,
            temperature=ready.temperature,
            daily_budget_cny=ready.daily_budget_cny,
            daily_call_cap=ready.daily_call_cap,
        )
    return SiliconFlowPresentationCopywriterAdapter.from_config(ready)


def build_text_understanding(
    *,
    semantic_intent=None,
    state_dir: str | os.PathLike[str] | None = None,
):
    """Assemble the text understanding port.

    - No ``GUIDE_LLM_API_KEY`` and no injected semantic port: exact-only
      understanding (identical to legacy ``understand_text`` behavior).
    - An explicitly injected semantic port enters ``ParallelUnderstanding``
      without inventing provider/model cache identity.
    - Key and selected model present: one-call SiliconFlow adapter +
      ``SingleCallUnderstanding``.
    - Key present without a selected model: typed configuration failure.

    The default runtime never imports a legacy LLM service; the SiliconFlow
    adapter is imported lazily only when a key is configured.
    """
    from app.guide.understanding.parallel_understanding import (
        ParallelUnderstanding,
    )
    from app.guide.understanding.text_understanding import (
        ExactOnlyTextUnderstanding,
    )
    from app.guide_runtime.llm_config import GuideLlmConfig

    config = GuideLlmConfig.from_environment()

    if semantic_intent is not None:
        return ParallelUnderstanding(
            semantic=semantic_intent,
        )

    if config.api_key is None:
        return ExactOnlyTextUnderstanding()
    ready = config.require_ready()

    from app.guide.adapters.llm.deepseek_intent import (
        DEEPSEEK_OFFICIAL_BASE_URL,
    )
    from app.guide.adapters.llm.deepseek_turn_meaning import (
        DeepSeekTurnMeaningAdapter,
    )
    from app.guide.adapters.llm.siliconflow_turn_meaning import (
        SiliconFlowTurnMeaningAdapter,
    )
    from app.guide.understanding.single_call_understanding import (
        SingleCallUnderstanding,
    )
    from app.guide.intent.concept_preferences import (
        ConceptPreferenceCatalog,
    )
    del state_dir
    concept_assets = build_selection_concept_assets()
    concept_catalog = tuple(
        sorted({
            item.concept_id
            for item in concept_assets.projections
        })
    )
    if ready.base_url == DEEPSEEK_OFFICIAL_BASE_URL:
        assert ready.api_key is not None
        assert ready.model is not None
        adapter = DeepSeekTurnMeaningAdapter(
            api_key=ready.api_key,
            model=ready.model,
            timeout_seconds=ready.timeout_seconds,
            max_tokens=ready.max_tokens,
            concept_catalog=concept_catalog,
            daily_budget_cny=ready.daily_budget_cny,
            daily_call_cap=ready.daily_call_cap,
        )
    else:
        adapter = SiliconFlowTurnMeaningAdapter.from_config(
            ready,
            concept_catalog=concept_catalog,
        )
    return SingleCallUnderstanding(
        semantic=adapter,
        concept_catalog=(
            ConceptPreferenceCatalog.from_projections(
                concept_assets.projections
            )
        ),
    )


def _assert_release_copywriter_validation() -> None:
    if "GUIDE_DEMO_RELAX_COPYWRITER_VALIDATION" in os.environ:
        raise RuntimeError(
            "GUIDE_DEMO_RELAX_COPYWRITER_VALIDATION is forbidden in release"
        )


def build_runtime_orchestrator(
    repo_root: Path = REPO_ROOT,
    *,
    state_dir: str | os.PathLike[str] | None = None,
    semantic_intent=None,
) -> TextRecommendationOrchestrator:
    _assert_release_copywriter_validation()
    canonical = repo_root / "data" / "canonical"
    reader = CanonicalProductReader.from_files(
        manifest_path=canonical / "core_products_v1_manifest.json",
        products_path=canonical / "core_products_v1.jsonl",
    )
    assets = load_seed_product_assets(
        manifest_path=canonical / "seed_product_images_v1_manifest.json",
        products_path=canonical / "seed_product_images_v1.jsonl",
        asset_root=repo_root,
    )
    state_root = _runtime_state_directory(state_dir)
    conversation_state = SqliteConversationState(
        state_root / "conversations.sqlite3",
        trusted_state_root=state_root,
    )
    public_conversation_state = PublicEventCommitConversationState(
        conversation_state
    )
    understanding = build_text_understanding(
        semantic_intent=semantic_intent,
        state_dir=state_root,
    )
    category_facts = build_category_fact_reader(
        reader,
        repo_root=repo_root,
    )
    product_evidence_reader = build_product_evidence_reader(repo_root)
    general_knowledge = GeneralKnowledgeRetriever(
        build_general_knowledge_assets(repo_root).blocks
    )
    return compose_text_recommendation_orchestrator(
        reader,
        product_assets=assets,
        conversation_state=public_conversation_state,
        review_evidence=build_review_evidence_reader(repo_root),
        category_fact_port=category_facts,
        product_display_bindings=(
            build_product_display_binding_reader(repo_root)
        ),
        product_evidence=build_product_evidence_retriever(
            repo_root,
            reader=product_evidence_reader,
        ),
        general_knowledge=general_knowledge,
        selection_facts=build_selection_fact_reader(
            category_facts=category_facts,
            product_evidence=product_evidence_reader,
        ),
        concept_reader=build_selection_parent_concept_reader(repo_root),
        controlled_product_aliases=(
            build_controlled_product_alias_registry(
                reader,
                repo_root=repo_root,
            )
        ),
        understanding=understanding,
        presentation_copywriter=build_presentation_copywriter(),
    )


def build_consultation_vertical_runtime(
    repo_root: Path = REPO_ROOT,
    *,
    state_dir: str | os.PathLike[str] | None = None,
    semantic_intent=None,
) -> ConsultationVerticalRuntime:
    _assert_release_copywriter_validation()
    canonical = repo_root / "data" / "canonical"
    reader = CanonicalProductReader.from_files(
        manifest_path=canonical / "core_products_v1_manifest.json",
        products_path=canonical / "core_products_v1.jsonl",
    )
    assets = load_seed_product_assets(
        manifest_path=canonical / "seed_product_images_v1_manifest.json",
        products_path=canonical / "seed_product_images_v1.jsonl",
        asset_root=repo_root,
    )
    state_root = _runtime_state_directory(state_dir)
    conversation_state = SqliteConversationState(
        state_root / "conversations.sqlite3",
        trusted_state_root=state_root,
    )
    public_conversation_state = PublicEventCommitConversationState(
        conversation_state
    )
    profile_state = SqliteProfileState(
        state_root / "profiles.sqlite3",
        trusted_state_root=state_root,
    )
    session_locks = InMemorySessionLocks()
    coordinator = ConsultationApplicationCoordinator(
        conversation_state=public_conversation_state,
        profile_state=profile_state,
    )
    understanding = build_text_understanding(
        semantic_intent=semantic_intent,
        state_dir=state_root,
    )
    category_facts = build_category_fact_reader(
        reader,
        repo_root=repo_root,
    )
    product_evidence_reader = build_product_evidence_reader(repo_root)
    general_knowledge = GeneralKnowledgeRetriever(
        build_general_knowledge_assets(repo_root).blocks
    )
    presentation_copywriter = build_presentation_copywriter()
    presentation_compiler = PresentationCompiler(
        copywriter=presentation_copywriter
    )
    consultation = ConsultationChatFlow(
        coordinator=coordinator,
        conversation_state=public_conversation_state,
        session_locks=session_locks,
        presentation_compiler=presentation_compiler,
    )
    recommendation = compose_text_recommendation_orchestrator(
        reader,
        product_assets=assets,
        conversation_state=public_conversation_state,
        session_locks=session_locks,
        profile_resolver=coordinator.resolve_turn_profile,
        review_evidence=build_review_evidence_reader(repo_root),
        category_fact_port=category_facts,
        product_display_bindings=(
            build_product_display_binding_reader(repo_root)
        ),
        product_evidence=build_product_evidence_retriever(
            repo_root,
            reader=product_evidence_reader,
        ),
        general_knowledge=general_knowledge,
        selection_facts=build_selection_fact_reader(
            category_facts=category_facts,
            product_evidence=product_evidence_reader,
        ),
        concept_reader=build_selection_parent_concept_reader(
            repo_root
        ),
        controlled_product_aliases=(
            build_controlled_product_alias_registry(
                reader,
                repo_root=repo_root,
            )
        ),
        understanding=understanding,
        presentation_copywriter=presentation_copywriter,
    )
    return ConsultationVerticalRuntime(
        consultation=consultation,
        recommendation=recommendation,
        unified=UnifiedGuideFlow(
            understanding=UnifiedUnderstandingAdapter(understanding),
            text_processor=recommendation,
            consultation_processor=consultation,
            conversation_state=public_conversation_state,
        ),
        presentation_compiler=presentation_compiler,
        conversation_state=conversation_state,
        profile_state=profile_state,
        profile_resolver=coordinator.resolve_turn_profile,
        session_locks=session_locks,
    )


def guide_image_runtime_lock():
    from app.guide.retrieval.image_contracts import ImageIndexRuntimeLock

    return ImageIndexRuntimeLock(
        manifest_sha256=GUIDE_IMAGE_MANIFEST_SHA256,
        model_name=GUIDE_IMAGE_MODEL_NAME,
        weights_sha256=GUIDE_IMAGE_WEIGHT_SHA256,
        preprocessing_version=GUIDE_IMAGE_PREPROCESSING_VERSION,
        vector_dimension=GUIDE_IMAGE_VECTOR_DIMENSION,
        index_sha256=GUIDE_IMAGE_INDEX_SHA256,
    )


def guide_image_weight_path() -> Path:
    configured = os.environ.get(GUIDE_IMAGE_WEIGHT_PATH_ENV)
    if configured:
        return Path(configured).expanduser()
    return (
        Path.home()
        / ".cache"
        / "huggingface"
        / "hub"
        / "models--laion--CLIP-ViT-B-32-laion2B-s34B-b79K"
        / "snapshots"
        / "1a25a446712ba5ee05982a381eed697ef9b435cf"
        / "open_clip_model.safetensors"
    )


def build_image_index_health_check(
    repo_root: Path = REPO_ROOT,
):
    from app.guide.adapters.image.index_runtime import (
        ImageIndexHealthCheck,
    )

    artifact_root = repo_root / GUIDE_IMAGE_ARTIFACT_RELATIVE_PATH
    return ImageIndexHealthCheck(
        manifest_path=artifact_root / "manifest.json",
        source_root=repo_root,
        artifact_root=artifact_root,
        runtime_lock=guide_image_runtime_lock(),
    )


def build_image_recommendation_orchestrator(
    *,
    repo_root: Path = REPO_ROOT,
    image_bundle_service: ImageBundleService,
    consultation_runtime: ConsultationVerticalRuntime | None = None,
    encoder: Any | None = None,
    weight_path: Path | None = None,
    device: str | None = None,
):
    _assert_release_copywriter_validation()
    from app.guide.adapters.catalog import CanonicalIdentityCatalog
    from app.guide.adapters.image.index_runtime import (
        HealthGuardedImageRetrieval,
    )
    from app.guide.adapters.image.local_numpy_index import (
        LocalNumpyImageIndex,
    )
    from app.guide.adapters.image.ocr_observation import (
        RapidOcrObservationAdapter,
    )
    from app.guide.adapters.image.openclip_adapter import (
        OpenClipImageEncoder,
        OpenClipModelSpec,
    )
    from app.guide.adapters.image.visual_observation import (
        ImageRetrievalVisualObservationAdapter,
    )
    from app.guide.application.image_recommendation_flow import (
        ImageRecommendationOrchestrator,
    )
    from app.guide.understanding.image_contracts import (
        IdentityBindingPolicy,
    )
    from app.guide.understanding.image_identity import ImageIdentityObserver

    canonical = repo_root / "data" / "canonical"
    reader = CanonicalProductReader.from_files(
        manifest_path=canonical / "core_products_v1_manifest.json",
        products_path=canonical / "core_products_v1.jsonl",
    )
    assets = load_seed_product_assets(
        manifest_path=canonical / "seed_product_images_v1_manifest.json",
        products_path=canonical / "seed_product_images_v1.jsonl",
        asset_root=repo_root,
    )
    category_facts = build_category_fact_reader(
        reader,
        repo_root=repo_root,
    )
    product_evidence_reader = build_product_evidence_reader(repo_root)
    catalog = CanonicalGuideCatalog(
        reader,
        product_assets=assets,
        category_fact_port=category_facts,
        selection_fact_port=build_selection_fact_reader(
            category_facts=category_facts,
            product_evidence=product_evidence_reader,
        ),
        product_display_bindings=(
            build_product_display_binding_reader(repo_root)
        ),
    )
    active_encoder = encoder
    if active_encoder is None:
        configured_device = device or os.environ.get(
            GUIDE_IMAGE_DEVICE_ENV
        )
        active_encoder = OpenClipImageEncoder(
            OpenClipModelSpec(
                weight_path=weight_path or guide_image_weight_path(),
                device=(
                    configured_device
                    or ("mps" if sys.platform == "darwin" else "cpu")
                ),
            )
        )
    artifact_root = repo_root / GUIDE_IMAGE_ARTIFACT_RELATIVE_PATH
    runtime_lock = guide_image_runtime_lock()
    health_check = build_image_index_health_check(repo_root)
    index = LocalNumpyImageIndex(
        manifest_path=artifact_root / "manifest.json",
        source_root=repo_root,
        artifact_root=artifact_root,
        runtime_lock=runtime_lock,
        encoder=active_encoder,
    )
    retrieval = HealthGuardedImageRetrieval(
        retrieval=index,
        health_check=health_check,
    )
    identity_observer = ImageIdentityObserver(
        visual_observation=ImageRetrievalVisualObservationAdapter(
            retrieval=retrieval
        ),
        ocr_observation=RapidOcrObservationAdapter(),
        canonical_identities=CanonicalIdentityCatalog(reader),
        policy=IdentityBindingPolicy(
            minimum_similarity=0.8,
            minimum_margin=0.1,
        ),
    )
    active_conversation_state = (
        consultation_runtime.recommendation._conversation_state
        if consultation_runtime is not None
        else None
    )
    if (
        active_conversation_state is not None
        and not isinstance(
            active_conversation_state,
            PublicEventCommitConversationState,
        )
    ):
        active_conversation_state = PublicEventCommitConversationState(
            active_conversation_state
        )
    return ImageRecommendationOrchestrator(
        image_bundles=image_bundle_service,
        identity_observer=identity_observer,
        category_catalog=catalog,
        scenario_evidence=catalog,
        decision_facts=catalog,
        presentation_facts=catalog,
        review_evidence=build_review_evidence_reader(repo_root),
        profile_owner_factory=(
            consultation_runtime.profile_owner
            if consultation_runtime is not None
            else None
        ),
        profile_resolver=(
            consultation_runtime.profile_resolver
            if consultation_runtime is not None
            else None
        ),
        conversation_state=active_conversation_state,
        session_locks=(
            consultation_runtime.session_locks
            if consultation_runtime is not None
            else None
        ),
        standard_processor=(
            consultation_runtime.recommendation
            if consultation_runtime is not None
            else None
        ),
        presentation_compiler=(
            consultation_runtime.presentation_compiler
            if consultation_runtime is not None
            else PresentationCompiler(
                copywriter=build_presentation_copywriter()
            )
        ),
        max_results=10,
    )


def build_image_recommendation_runtime(
    *,
    repo_root: Path = REPO_ROOT,
    image_bundle_service: ImageBundleService,
    consultation_runtime: ConsultationVerticalRuntime | None = None,
    consultation_runtime_provider: (
        Callable[[], ConsultationVerticalRuntime] | None
    ) = None,
):
    from app.guide_runtime.image_runtime import ImageRecommendationRuntime

    return ImageRecommendationRuntime(
        builder=lambda: build_image_recommendation_orchestrator(
            repo_root=repo_root,
            image_bundle_service=image_bundle_service,
            consultation_runtime=(
                consultation_runtime_provider()
                if consultation_runtime_provider is not None
                else consultation_runtime
            ),
        ),
        health_check=build_image_index_health_check(repo_root),
        runtime_lock=guide_image_runtime_lock(),
    )
