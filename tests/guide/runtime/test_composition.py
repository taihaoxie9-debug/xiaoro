from __future__ import annotations

from collections import Counter
import hashlib
import json
import os
from pathlib import Path

import numpy as np
import pytest

from app.guide.adapters.image.ocr_observation import (
    RapidOcrObservationAdapter,
)
from app.guide.adapters.image.safe_image_input import UntrustedImageInput
from app.guide.adapters.state.in_memory_image_bundle_state import (
    InMemoryImageBundleState,
)
from app.guide.application.contracts import UserTurn
from app.guide.application.image_bundle_service import ImageBundleService
from app.guide.retrieval.image_contracts import ApprovedImageModelLock
from app.guide.retrieval.category_fact_reader import CategoryFactReader
from app.guide.retrieval.category_profiles import (
    CategoryProfile,
    category_profile_for,
)
from app.guide.retrieval.merchant_claim_reader import (
    ClaimAugmentedCategoryFactReader,
)
from app.guide.retrieval.selection_fact_reader import SelectionFactReader
from app.guide.retrieval.general_knowledge_assets import (
    GeneralKnowledgeAssets,
)
from app.guide_runtime.composition import (
    REPO_ROOT,
    build_image_recommendation_orchestrator,
    build_runtime_orchestrator,
    guide_image_runtime_lock,
)
from tests.guide.semantic_test_port import ExactEchoSemanticPort

EXPECTED_CATEGORY_FACT_MANIFEST_SHA256 = (
    "56e10e7dc066910b3d1f1aba65c4002b030a918172601c1ba643376457e7f438"
)
EXPECTED_MERCHANT_CLAIM_MANIFEST_SHA256 = (
    "d906c0a6d42636c89d1ccb408413c786b817cbb2ddf44678143c427228a21e75"
)
EXPECTED_PRODUCT_EVIDENCE_MANIFEST_SHA256 = (
    "ca5cee9dc0e70e64f3e30b2faf7aed35d45fae45272a299c540bfb79d071b351"
)
EXPECTED_GENERAL_KNOWLEDGE_MANIFEST_SHA256 = (
    "09bea87c4c56f18b982f474a42ef1ca0abd758da8b90a73a34681ec7c605ac21"
)
EXPECTED_SELECTION_CONCEPT_MANIFEST_SHA256 = (
    "2783fb241c5f3be60bcb70425e67b20df65bb03af82bd2b62c3d75875a7e2f95"
)
EXPECTED_PRODUCT_DISPLAY_MANIFEST_SHA256 = (
    "1453be0d77db36914ad64901ab94ffb8fc269df3cd1fc4911912cfe5476631c2"
)


def test_category_fact_manifest_lock_matches_logical_self_hash() -> None:
    from app.guide_runtime import composition

    assert composition.GUIDE_CATEGORY_FACT_RELATIVE_PATH == (
        Path("data")
        / "guide_category_facts"
        / "category_facts_v1_manifest.json"
    )
    assert composition.GUIDE_CATEGORY_FACT_MANIFEST_SHA256 == (
        EXPECTED_CATEGORY_FACT_MANIFEST_SHA256
    )
    manifest_path = (
        REPO_ROOT / composition.GUIDE_CATEGORY_FACT_RELATIVE_PATH
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    unsigned = {
        key: value
        for key, value in manifest.items()
        if key != "manifest_sha256"
    }
    logical_self_hash = hashlib.sha256(
        json.dumps(
            unsigned,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()

    assert manifest["manifest_sha256"] == (
        EXPECTED_CATEGORY_FACT_MANIFEST_SHA256
    )
    assert logical_self_hash == EXPECTED_CATEGORY_FACT_MANIFEST_SHA256


def test_merchant_claim_manifest_lock_matches_logical_self_hash() -> None:
    from app.guide_runtime import composition

    assert composition.GUIDE_MERCHANT_CLAIM_RELATIVE_PATH == (
        Path("data")
        / "guide_merchant_claims"
        / "merchant_claims_v1_manifest.json"
    )
    assert composition.GUIDE_MERCHANT_CLAIM_MANIFEST_SHA256 == (
        EXPECTED_MERCHANT_CLAIM_MANIFEST_SHA256
    )
    manifest_path = (
        REPO_ROOT / composition.GUIDE_MERCHANT_CLAIM_RELATIVE_PATH
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    unsigned = {
        key: value
        for key, value in manifest.items()
        if key != "manifest_sha256"
    }
    logical_self_hash = hashlib.sha256(
        json.dumps(
            unsigned,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()

    assert manifest["manifest_sha256"] == (
        EXPECTED_MERCHANT_CLAIM_MANIFEST_SHA256
    )
    assert (
        logical_self_hash
        == EXPECTED_MERCHANT_CLAIM_MANIFEST_SHA256
    )


def test_product_evidence_manifest_lock_is_composed_into_runtime(
    tmp_path: Path,
) -> None:
    from app.guide.retrieval.product_evidence_retrieval import (
        ProductEvidenceRetriever,
    )
    from app.guide_runtime import composition

    assert composition.GUIDE_PRODUCT_EVIDENCE_RELATIVE_PATH == (
        Path("data")
        / "guide_product_evidence"
        / "product_evidence_v1_manifest.json"
    )
    assert composition.GUIDE_PRODUCT_EVIDENCE_MANIFEST_SHA256 == (
        EXPECTED_PRODUCT_EVIDENCE_MANIFEST_SHA256
    )
    orchestrator = composition.build_runtime_orchestrator(
        state_dir=tmp_path / "state",
    )
    assert isinstance(
        orchestrator._product_evidence,
        ProductEvidenceRetriever,
    )
    assert (
        orchestrator._product_evidence._reader.manifest.manifest_sha256
        == EXPECTED_PRODUCT_EVIDENCE_MANIFEST_SHA256
    )


def test_runtime_composes_manifest_bound_controlled_product_aliases(
    tmp_path: Path,
) -> None:
    orchestrator = build_runtime_orchestrator(
        state_dir=tmp_path / "state",
    )
    resolver = orchestrator._product_name_resolver

    assert resolver is not None
    assert resolver._controlled_aliases is not None
    assert (
        resolver._controlled_aliases.default_product_id("神仙水")
        == 59
    )
    assert (
        resolver._controlled_aliases.default_product_id("小白管")
        is None
    )
    assert resolver._controlled_aliases.candidate_product_ids(
        "小白管"
    ) == (101, 130)


def test_general_knowledge_manifest_lock_is_available_to_runtime() -> None:
    from app.guide_runtime import composition

    assert composition.GUIDE_GENERAL_KNOWLEDGE_RELATIVE_PATH == (
        Path("data")
        / "guide_general_knowledge"
        / "general_knowledge_v1_manifest.json"
    )
    assert composition.GUIDE_GENERAL_KNOWLEDGE_MANIFEST_SHA256 == (
        EXPECTED_GENERAL_KNOWLEDGE_MANIFEST_SHA256
    )
    assets = composition.build_general_knowledge_assets()

    assert isinstance(assets, GeneralKnowledgeAssets)
    assert len(assets.blocks) == 209
    assert (
        assets.manifest.manifest_sha256
        == EXPECTED_GENERAL_KNOWLEDGE_MANIFEST_SHA256
    )


def test_selection_concept_manifest_lock_is_available_to_runtime() -> None:
    from app.guide.retrieval.selection_parent_concept_assets import (
        SelectionConceptAssets,
    )
    from app.guide.retrieval.selection_parent_concept_reader import (
        SelectionParentConceptReader,
    )
    from app.guide_runtime import composition

    assert composition.GUIDE_SELECTION_CONCEPT_RELATIVE_PATH == (
        Path("data")
        / "guide_selection_concepts"
        / "v2"
        / "selection_concepts_v1_manifest.json"
    )
    assert composition.GUIDE_SELECTION_CONCEPT_MANIFEST_SHA256 == (
        EXPECTED_SELECTION_CONCEPT_MANIFEST_SHA256
    )
    assets = composition.build_selection_concept_assets()
    reader = composition.build_selection_parent_concept_reader()

    assert isinstance(assets, SelectionConceptAssets)
    assert len(assets.projections) == 188
    assert (
        assets.manifest.manifest_sha256
        == EXPECTED_SELECTION_CONCEPT_MANIFEST_SHA256
    )
    assert isinstance(reader, SelectionParentConceptReader)
    assert len(reader._index) == 188


def test_runtime_selection_concepts_cover_terminal_review_maps() -> None:
    from app.guide_runtime import composition

    assets = composition.build_selection_concept_assets()
    projections = {
        (
            item.profile.value,
            item.field_key,
            item.normalized_value.casefold(),
        ): item
        for item in assets.projections
    }
    reviewed_mappings = tuple(
        json.loads(line)
        for line in (
            REPO_ROOT
            / "docs"
            / "audits"
            / "selection-concepts"
            / "review-v2"
            / "reviewed_mappings.jsonl"
        ).read_text(encoding="utf-8").splitlines()
        if line.strip()
    )

    assert assets.manifest.review_count == 191
    assert assets.manifest.projection_count == 188
    assert assets.manifest.concept_count == 50
    assert {
        "texture.rich_cream",
        "texture.silky",
    } <= {
        item.concept_id for item in assets.projections
    }
    assert all(
        mapping["product_id"]
        in projections[(
            mapping["profile"],
            mapping["field_key"],
            mapping["normalized_value"].casefold(),
        )].product_ids
        and projections[(
            mapping["profile"],
            mapping["field_key"],
            mapping["normalized_value"].casefold(),
        )].concept_id
        == mapping["concept_id"]
        for mapping in reviewed_mappings
    )


def test_selection_concept_sources_track_current_selection_facts() -> None:
    from app.guide_runtime import composition

    orchestrator = composition.build_runtime_orchestrator()
    catalog = orchestrator._presentation_facts
    concept_reader = composition.build_selection_parent_concept_reader()

    for product_id in sorted(catalog._reader.product_ids):
        product = catalog._reader.get(product_id)
        profile = category_profile_for(
            product.fields["category"].value
        )
        facts = catalog._selection_fact_port.read(
            product_id=product_id,
            profile=profile,
        )
        concept_reader.project(facts)


def test_runtime_projects_new_concepts_and_excludes_leave_free() -> None:
    from app.guide_runtime import composition

    orchestrator = composition.build_runtime_orchestrator()
    catalog = orchestrator._presentation_facts
    concept_reader = composition.build_selection_parent_concept_reader()

    projected_by_product = {}
    selection_by_product = {}
    for product_id in (37, 49, 120):
        product = catalog._reader.get(product_id)
        profile = category_profile_for(
            product.fields["category"].value
        )
        selection_facts = catalog._selection_fact_port.read(
            product_id=product_id,
            profile=profile,
        )
        selection_by_product[product_id] = selection_facts
        projected_by_product[product_id] = {
            item.concept_id
            for item in concept_reader.project(selection_facts)
        }

    fragrance_profile = category_profile_for(
        catalog._reader.get(120).fields["category"].value
    )
    concentration = next(
        item
        for item in catalog._category_fact_port.base.read(
            product_id=120,
            profile=fragrance_profile,
        )
        if item.field_key == "concentration"
    )

    assert "texture.silky" in projected_by_product[37]
    assert "texture.rich_cream" in projected_by_product[49]
    assert concentration.capabilities == frozenset(
        {"evidence", "display"}
    )
    assert not set(concentration.source_refs).intersection(
        reference
        for item in selection_by_product[120]
        for reference in item.source_refs
    )


def test_runtime_uses_reviewed_display_and_price_sku_bindings(
    tmp_path: Path,
) -> None:
    orchestrator = build_runtime_orchestrator(
        state_dir=tmp_path / "display-bindings",
    )

    conflicted = orchestrator._presentation_facts.get_presentation_facts(
        91
    )
    aligned = orchestrator._presentation_facts.get_presentation_facts(52)

    assert conflicted.display_name == "玉泽皮肤屏障修护精华乳"
    assert conflicted.specification is None
    assert aligned.display_name == "兰蔻菁纯臻颜防晒隔离乳"
    assert aligned.specification == "30ml"


def test_release_runtime_rejects_demo_copywriter_validation_bypass(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv(
        "GUIDE_DEMO_RELAX_COPYWRITER_VALIDATION",
        "true",
    )

    with pytest.raises(
        RuntimeError,
        match="forbidden in release",
    ):
        build_runtime_orchestrator(
            state_dir=tmp_path / "forbidden-demo-bypass",
        )


def test_product_display_manifest_lock_matches_logical_self_hash() -> None:
    from app.guide_runtime import composition

    manifest_path = (
        REPO_ROOT / composition.GUIDE_PRODUCT_DISPLAY_RELATIVE_PATH
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    unsigned = {
        key: value
        for key, value in manifest.items()
        if key != "manifest_sha256"
    }
    logical_self_hash = hashlib.sha256(
        json.dumps(
            unsigned,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()

    assert composition.GUIDE_PRODUCT_DISPLAY_MANIFEST_SHA256 == (
        EXPECTED_PRODUCT_DISPLAY_MANIFEST_SHA256
    )
    assert manifest["manifest_sha256"] == (
        EXPECTED_PRODUCT_DISPLAY_MANIFEST_SHA256
    )
    assert logical_self_hash == EXPECTED_PRODUCT_DISPLAY_MANIFEST_SHA256


def test_product_display_runtime_lock_rejects_drift(
    monkeypatch,
) -> None:
    from app.guide_runtime import composition

    monkeypatch.setattr(
        composition,
        "GUIDE_PRODUCT_DISPLAY_MANIFEST_SHA256",
        "0" * 64,
    )

    with pytest.raises(ValueError, match="runtime manifest lock"):
        composition.build_product_display_binding_reader()


def test_selection_concept_runtime_lock_rejects_drift(
    monkeypatch,
) -> None:
    from app.guide_runtime import composition

    monkeypatch.setattr(
        composition,
        "GUIDE_SELECTION_CONCEPT_MANIFEST_SHA256",
        "0" * 64,
    )

    with pytest.raises(ValueError, match="runtime manifest lock"):
        composition.build_selection_concept_assets()


def test_runtime_loads_general_knowledge_once(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from app.guide_runtime import composition

    real_loader = composition.load_general_knowledge_assets
    calls = 0

    def load_once(*args, **kwargs):
        nonlocal calls
        calls += 1
        return real_loader(*args, **kwargs)

    monkeypatch.setattr(
        composition,
        "load_general_knowledge_assets",
        load_once,
    )
    orchestrator = composition.build_runtime_orchestrator(
        state_dir=tmp_path / "state",
    )

    assert calls == 1
    assert orchestrator._general_knowledge is not None
    assert len(orchestrator._general_knowledge.blocks) == 209


def test_runtime_reuses_locked_readers_for_unified_selection_facts(
    tmp_path: Path,
) -> None:
    orchestrator = build_runtime_orchestrator(
        state_dir=tmp_path / "state",
    )
    catalog = orchestrator._decision_facts
    category_facts = catalog._category_fact_port
    selection_facts = catalog._selection_fact_port

    assert isinstance(
        category_facts,
        ClaimAugmentedCategoryFactReader,
    )
    assert isinstance(selection_facts, SelectionFactReader)
    assert selection_facts._base is category_facts.base
    assert selection_facts._claims is category_facts.claims
    assert (
        selection_facts._evidence
        is orchestrator._product_evidence._reader
    )


def test_runtime_selection_facts_cover_full_catalog_without_loss(
    tmp_path: Path,
) -> None:
    orchestrator = build_runtime_orchestrator(
        state_dir=tmp_path / "state",
    )
    catalog = orchestrator._decision_facts
    selection_facts = catalog._selection_fact_port
    counts: Counter[object] = Counter()

    for product_id in sorted(catalog._reader.product_ids):
        product = catalog._reader.get(product_id)
        profile = category_profile_for(
            product.fields["category"].value
        )
        facts = selection_facts.read(
            product_id=product_id,
            profile=profile,
        )
        decision_facts = catalog.get_decision_facts(product_id)
        assert decision_facts.selection_facts == facts
        assert len(facts) == len(
            {item.selection_key for item in facts}
        )
        counts["total"] += len(facts)
        counts.update(item.rank_strength for item in facts)
        counts.update(item.safety_role for item in facts)

    assert counts["total"] == 2435
    assert counts[1] == 1312
    assert counts[2] == 557
    assert counts[None] == 566
    assert counts["merchant_positive_safety"] == 156
    assert counts["verified_warning"] == 41


def test_runtime_loads_each_selection_asset_once(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from app.guide_runtime import composition

    category_loader = composition.load_category_fact_assets
    claim_loader = composition.load_merchant_claim_assets
    evidence_loader = composition.load_product_evidence_assets
    calls = {
        "category": 0,
        "claims": 0,
        "evidence": 0,
    }

    def load_category(**kwargs):
        calls["category"] += 1
        return category_loader(**kwargs)

    def load_claims(**kwargs):
        calls["claims"] += 1
        return claim_loader(**kwargs)

    def load_evidence(**kwargs):
        calls["evidence"] += 1
        return evidence_loader(**kwargs)

    monkeypatch.setattr(
        composition,
        "load_category_fact_assets",
        load_category,
    )
    monkeypatch.setattr(
        composition,
        "load_merchant_claim_assets",
        load_claims,
    )
    monkeypatch.setattr(
        composition,
        "load_product_evidence_assets",
        load_evidence,
    )

    composition.build_runtime_orchestrator(
        state_dir=tmp_path / "state",
    )

    assert calls == {
        "category": 1,
        "claims": 1,
        "evidence": 1,
    }


def test_runtime_category_facts_include_reviewed_ocr_soft_rank() -> None:
    from app.guide_runtime import composition

    canonical = REPO_ROOT / "data" / "canonical"
    reader = composition.CanonicalProductReader.from_files(
        manifest_path=canonical / "core_products_v1_manifest.json",
        products_path=canonical / "core_products_v1.jsonl",
    )
    facts = composition.build_category_fact_reader(reader).read(
        product_id=57,
        profile=CategoryProfile.SUNCARE,
    )
    finish = next(item for item in facts if item.field_key == "finish")

    assert finish.resolved_state == "known"
    assert "清爽不易搓泥" in finish.value
    assert "soft_rank" in finish.capabilities
    assert "hard_filter" not in finish.capabilities


def test_category_fact_reader_is_loaded_once_per_runtime_composition(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from app.guide_runtime import composition

    real_loader = composition.load_category_fact_assets
    load_calls: list[Path] = []

    def load_once(**kwargs):
        load_calls.append(Path(kwargs["manifest_path"]))
        return real_loader(**kwargs)

    monkeypatch.setattr(
        composition,
        "load_category_fact_assets",
        load_once,
    )

    text = composition.build_runtime_orchestrator(
        state_dir=tmp_path / "text-state",
    )
    assert len(load_calls) == 1
    _assert_single_category_fact_reader(text)

    consultation = composition.build_consultation_vertical_runtime(
        state_dir=tmp_path / "consultation-state",
    )
    assert len(load_calls) == 2
    _assert_single_category_fact_reader(consultation.recommendation)

    image_service = ImageBundleService(
        state=InMemoryImageBundleState(max_bundles=2)
    )
    image = composition.build_image_recommendation_orchestrator(
        repo_root=REPO_ROOT,
        image_bundle_service=image_service,
        encoder=StoredVectorEncoder(53),
    )
    assert len(load_calls) == 3
    _assert_single_category_fact_reader(image)
    assert load_calls == [
        (
            REPO_ROOT
            / "data"
            / "guide_category_facts"
            / "category_facts_v1_manifest.json"
        )
    ] * 3


def _assert_single_category_fact_reader(orchestrator: object) -> None:
    catalogs = (
        orchestrator._category_catalog,
        orchestrator._scenario_evidence,
        orchestrator._decision_facts,
        orchestrator._presentation_facts,
    )
    assert all(catalog is catalogs[0] for catalog in catalogs)
    assert isinstance(
        catalogs[0]._category_fact_port,
        ClaimAugmentedCategoryFactReader,
    )
    assert isinstance(
        catalogs[0]._category_fact_port._base,
        CategoryFactReader,
    )


def test_runtime_composition_uses_repo_absolute_assets(
    tmp_path: Path,
) -> None:
    previous = Path.cwd()
    os.chdir(tmp_path)
    try:
        orchestrator = build_runtime_orchestrator(
            state_dir=tmp_path / "state",
            semantic_intent=ExactEchoSemanticPort(),
        )
        events = list(
            orchestrator.stream(
                UserTurn(
                    session_id="composition-test",
                    message="500 内适合油敏肌的防晒",
                    image_bundle_id=None,
                    conversation_version=0,
                )
            )
        )
    finally:
        os.chdir(previous)

    products = next(event for event in events if event.event == "products")
    assert [card.product_id for card in products.data.cards] == [101, 26, 52]
    assert products.data.cards[0].image_url == (
        "/static/images/products/jd_v3_100222404954.png"
    )
    assert REPO_ROOT == Path(__file__).resolve().parents[3]


def test_repair_serum_composition_uses_repo_absolute_assets(
    tmp_path: Path,
) -> None:
    previous = Path.cwd()
    os.chdir(tmp_path)
    try:
        orchestrator = build_runtime_orchestrator(
            state_dir=tmp_path / "state",
            semantic_intent=ExactEchoSemanticPort(),
        )
        events = list(
            orchestrator.stream(
                UserTurn(
                    session_id="serum-composition-test",
                    message="500 元内敏感肌修护精华",
                    image_bundle_id=None,
                    conversation_version=0,
                )
            )
        )
    finally:
        os.chdir(previous)

    products = next(event for event in events if event.event == "products")
    assert [card.product_id for card in products.data.cards] == [38, 91]
    assert all(
        card.matched_efficacies == ["修护"]
        for card in products.data.cards
    )
    assert all(card.image_url for card in products.data.cards)


def test_followup_composition_retains_state_outside_repo(
    tmp_path: Path,
) -> None:
    previous = Path.cwd()
    os.chdir(tmp_path)
    try:
        orchestrator = build_runtime_orchestrator(
            state_dir=tmp_path / "state",
            semantic_intent=ExactEchoSemanticPort(),
        )
        first = list(
            orchestrator.stream(
                UserTurn(
                    session_id="followup-composition-test",
                    message="500 元内敏感肌修护精华",
                    image_bundle_id=None,
                    conversation_version=0,
                )
            )
        )
        second = list(
            orchestrator.stream(
                UserTurn(
                    session_id="followup-composition-test",
                    message="第二款呢",
                    image_bundle_id=None,
                    conversation_version=1,
                )
            )
        )
    finally:
        os.chdir(previous)

    assert first[-1].data.conversation_version == 1
    products = next(
        event for event in second if event.event == "products"
    )
    assert [card.product_id for card in products.data.cards] == [91]
    assert second[-1].data.conversation_version == 2


def test_budget_revision_composition_retains_query_context_outside_repo(
    tmp_path: Path,
) -> None:
    previous = Path.cwd()
    os.chdir(tmp_path)
    try:
        orchestrator = build_runtime_orchestrator(
            state_dir=tmp_path / "state",
            semantic_intent=ExactEchoSemanticPort(),
        )
        first = list(
            orchestrator.stream(
                UserTurn(
                    session_id="budget-composition-test",
                    message="500 元内敏感肌修护精华",
                    image_bundle_id=None,
                    conversation_version=0,
                )
            )
        )
        second = list(
            orchestrator.stream(
                UserTurn(
                    session_id="budget-composition-test",
                    message="预算降到100元呢",
                    image_bundle_id=None,
                    conversation_version=1,
                )
            )
        )
    finally:
        os.chdir(previous)

    assert first[-1].data.conversation_version == 1
    products = next(
        item for item in second if item.event == "products"
    )
    assert [card.product_id for card in products.data.cards] == [91]
    assert second[-1].data.conversation_version == 2


class StoredVectorEncoder:
    def __init__(
        self,
        requested_product_ids: int | tuple[int, ...],
    ) -> None:
        lock = guide_image_runtime_lock()
        self.model_lock = ApprovedImageModelLock(
            approval_id="slice2.0-model-gate-2026-08-08",
            model_name=lock.model_name,
            weights_sha256=lock.weights_sha256,
            preprocessing_version=lock.preprocessing_version,
            vector_dimension=lock.vector_dimension,
        )
        root = (
            REPO_ROOT
            / "data"
            / "guide_image_index"
            / "openclip_vit_b32_laion2b_s34b_b79k_v1"
        )
        manifest = json.loads(
            (root / "manifest.json").read_text(encoding="utf-8")
        )
        product_ids = [
            entry["product_id"] for entry in manifest["entries"]
        ]
        matrix = np.load(root / "index.npy", allow_pickle=False)
        requested_ids = (
            (requested_product_ids,)
            if isinstance(requested_product_ids, int)
            else requested_product_ids
        )
        self._vectors = tuple(
            matrix[product_ids.index(product_id)]
            for product_id in requested_ids
        )
        self._calls = 0

    def encode_bytes(self, content: bytes) -> np.ndarray:
        assert content
        index = min(self._calls, len(self._vectors) - 1)
        self._calls += 1
        return self._vectors[index].copy()


def test_image_composition_uses_approved_rapidocr_adapter() -> None:
    service = ImageBundleService(
        state=InMemoryImageBundleState(max_bundles=4)
    )

    orchestrator = build_image_recommendation_orchestrator(
        repo_root=REPO_ROOT,
        image_bundle_service=service,
        encoder=StoredVectorEncoder(53),
    )

    assert isinstance(
        orchestrator._identity_observer._ocr_observation,
        RapidOcrObservationAdapter,
    )


def test_text_and_image_compositions_use_approved_review_assets(
    tmp_path: Path,
) -> None:
    service = ImageBundleService(
        state=InMemoryImageBundleState(max_bundles=4)
    )
    orchestrators = (
        build_runtime_orchestrator(
            state_dir=tmp_path / "text-state",
        ),
        build_image_recommendation_orchestrator(
            repo_root=REPO_ROOT,
            image_bundle_service=service,
            encoder=StoredVectorEncoder(53),
        ),
    )

    for orchestrator in orchestrators:
        positive = orchestrator._review_evidence.read(product_id=55)
        absent = orchestrator._review_evidence.read(product_id=57)

        assert [item.source_id for item in positive.evidence] == [
            (
                "review_tmall_item_746513552108_html_"
                "56719aa64a4222a961b2ea118cf51415f25c4f88560e5de83172adc8e9c13783_"
                "ordinal_00000001"
            ),
            (
                "review_tmall_item_746513552108_html_"
                "56719aa64a4222a961b2ea118cf51415f25c4f88560e5de83172adc8e9c13783_"
                "ordinal_00000002"
            ),
        ]
        assert positive.verified_absence is None
        assert absent.evidence == []
        assert absent.verified_absence is not None
        assert absent.verified_absence.product_id == 57


def test_image_composition_uses_locked_index_and_real_product_cards() -> None:
    lock = guide_image_runtime_lock()
    assert lock.manifest_sha256 == (
        "f47e183aaec1f8418f9d4dcef78481607ab4a74d38b46920025c23070a3427d9"
    )
    assert lock.index_sha256 == (
        "f61ba8ed45dc6f3d285e22016f7c643bfd01eec78ba65c84e75e5fabb843d340"
    )
    service = ImageBundleService(
        state=InMemoryImageBundleState(max_bundles=2)
    )
    source = (
        REPO_ROOT
        / "app"
        / "static"
        / "images"
        / "products"
        / "taobao_v3_572910260362.png"
    )
    receipt = service.create(
        session_id="image-composition",
        images=[
            UntrustedImageInput(
                file_name=source.name,
                declared_media_type="image/png",
                content=source.read_bytes(),
            )
        ],
    )
    orchestrator = build_image_recommendation_orchestrator(
        repo_root=REPO_ROOT,
        image_bundle_service=service,
        encoder=StoredVectorEncoder(53),
    )

    events = list(
        orchestrator.stream(
            UserTurn(
                session_id="image-composition",
                message="150元以内找相似款",
                image_bundle_id=receipt.bundle_id,
                image_bundle_version=receipt.version,
                image_bundle_token=receipt.owner_token,
                conversation_version=0,
            )
        )
    )

    observation = next(
        event
        for event in events
        if event.event == "image_observation"
    )
    products = next(
        event for event in events if event.event == "products"
    )
    assert observation.data.observation.confirmed_product_id == 53
    assert observation.data.observation.index_sha256 == lock.index_sha256
    assert [card.product_id for card in products.data.cards] == [54]
    assert all(card.image_url for card in products.data.cards)
    assert all(card.detail_url for card in products.data.cards)
