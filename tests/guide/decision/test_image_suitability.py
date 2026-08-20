from __future__ import annotations

import importlib
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.guide.adapters.catalog import CanonicalProductReader
from app.guide.adapters.catalog.canonical_guide_catalog import (
    CanonicalGuideCatalog,
)
from app.guide.decision.contracts import DecisionProductFacts, FactState
from app.guide.feedback.profile_contracts import ProfileOwnerRef
from app.guide.retrieval.category_profiles import CategoryProfile


ROOT = Path(__file__).resolve().parents[3]


def _contracts():
    try:
        return importlib.import_module(
            "app.guide.decision.image_suitability_contracts"
        )
    except ModuleNotFoundError:
        pytest.fail("image suitability contracts are missing")


def _subject():
    try:
        return importlib.import_module(
            "app.guide.decision.image_suitability"
        )
    except ModuleNotFoundError:
        pytest.fail("image suitability decision is missing")


_BUNDLE_ID = "bundle_" + "a" * 32
_IMAGE_ID = "image_" + "1" * 32
_SESSION_ID = "session-current"
_PROFILE_OWNER = ProfileOwnerRef(
    scope="local_demo",
    subject_id="profile_0123456789abcdef",
)


def _claim(
    contracts,
    *,
    source,
    skin_target: str,
    evidence_ref: str,
):
    profile_data = (
        {
            "profile_owner": _PROFILE_OWNER,
            "profile_version": 3,
            "profile_confirmed": True,
        }
        if source is contracts.SuitabilityContextSource.LONG_TERM_PROFILE
        else {}
    )
    return contracts.SuitabilityContextClaim(
        skin_target=skin_target,
        provenance=contracts.SuitabilityContextProvenance(
            current_bundle_id=_BUNDLE_ID,
            current_image_id=_IMAGE_ID,
            session_id=_SESSION_ID,
            conversation_version=7,
            source_kind=source,
            evidence_ref=evidence_ref,
            **profile_data,
        ),
    )


def test_context_resolution_uses_current_explicit_before_session_and_profile(
) -> None:
    contracts = _contracts()
    claims = contracts.SuitabilityContextClaims(
        claims=(
            _claim(
                contracts,
                source=(
                    contracts.SuitabilityContextSource.LONG_TERM_PROFILE
                ),
                skin_target="sensitive",
                evidence_ref="profile:local_demo:version=3#skin_type",
            ),
            _claim(
                contracts,
                source=(
                    contracts.SuitabilityContextSource.CONFIRMED_SESSION
                ),
                skin_target="combination",
                evidence_ref="session:test:version=7#confirmed_skin",
            ),
            _claim(
                contracts,
                source=(
                    contracts.SuitabilityContextSource
                    .CURRENT_EXPLICIT_INPUT
                ),
                skin_target="dry",
                evidence_ref="turn:current#skin",
            ),
        )
    )

    result = _subject().resolve_suitability_context(claims)

    assert result.kind == "resolved"
    assert result.context.source.value == "current_explicit_input"
    assert result.context.precedence == 1
    assert result.context.skin_target.value == "dry"
    assert result.context.evidence_ref == "turn:current#skin"


def _resolved_context(*, skin_target: str = "sensitive"):
    contracts = _contracts()
    resolution = _subject().resolve_suitability_context(
        contracts.SuitabilityContextClaims(
            claims=(
                _claim(
                    contracts,
                    source=(
                        contracts.SuitabilityContextSource
                        .CURRENT_EXPLICIT_INPUT
                    ),
                    skin_target=skin_target,
                    evidence_ref="turn:current#skin",
                ),
            )
        )
    )
    assert resolution.context is not None
    return resolution.context


def _facts(
    *,
    suitable_skin: tuple[str, ...] | None = ("敏感肌适用",),
    suitable_skin_state: FactState = FactState.KNOWN,
    source_refs: tuple[str, ...] = (
        "data/seed_dump.sql#product=53",
    ),
) -> DecisionProductFacts:
    return DecisionProductFacts(
        product_id=53,
        category_profile=CategoryProfile.SUNCARE,
        category_fields=(),
        price=None,
        price_state=FactState.UNKNOWN,
        efficacy=None,
        efficacy_state=FactState.UNKNOWN,
        suitable_skin=suitable_skin,
        suitable_skin_state=suitable_skin_state,
        ingredients_present=None,
        ingredients_present_state=FactState.UNKNOWN,
        verified_absences=None,
        verified_absences_state=FactState.UNKNOWN,
        suitable_skin_source_refs=source_refs,
    )


def _decide_for_skin_text(
    canonical_skin: tuple[str, ...],
    *,
    skin_target: str = "sensitive",
):
    contracts = _contracts()
    request = contracts.ImageSuitabilityDecisionInput(
        reference=contracts.ImageSuitabilityDecisionReference(
            ordinal=1,
            image_id="image_" + "1" * 32,
            product_id=53,
        ),
        context=_resolved_context(skin_target=skin_target),
        facts=_facts(suitable_skin=canonical_skin),
    )
    return _subject().ImageSuitabilityDecisionFoundation().decide(request)


def _decide_for_facts(
    facts: DecisionProductFacts,
    *,
    skin_target: str,
):
    contracts = _contracts()
    request = contracts.ImageSuitabilityDecisionInput(
        reference=contracts.ImageSuitabilityDecisionReference(
            ordinal=1,
            image_id="image_" + "1" * 32,
            product_id=facts.product_id,
        ),
        context=_resolved_context(skin_target=skin_target),
        facts=facts,
    )
    return _subject().ImageSuitabilityDecisionFoundation().decide(request)


@pytest.fixture(scope="module")
def real_catalog() -> CanonicalGuideCatalog:
    canonical = ROOT / "data" / "canonical"
    reader = CanonicalProductReader.from_files(
        manifest_path=canonical / "core_products_v1_manifest.json",
        products_path=canonical / "core_products_v1.jsonl",
    )
    return CanonicalGuideCatalog(reader)


def test_auditable_canonical_match_is_suitable_with_one_card_intent() -> None:
    contracts = _contracts()
    request = contracts.ImageSuitabilityDecisionInput(
        reference=contracts.ImageSuitabilityDecisionReference(
            ordinal=1,
            image_id="image_" + "1" * 32,
            product_id=53,
        ),
        context=_resolved_context(),
        facts=_facts(),
    )

    result = _subject().ImageSuitabilityDecisionFoundation().decide(request)

    assert result.status == "suitable"
    assert result.reference == request.reference
    assert result.context == request.context
    assert result.card_intent.mode == "single"
    assert result.card_intent.visible_product_ids == (53,)
    assert result.card_intent.reason == "product"
    assert result.evidence_refs == (
        "turn:current#skin",
        "data/seed_dump.sql#product=53",
    )


@pytest.mark.parametrize(
    "canonical_skin",
    [
        ("干性肌肤适用",),
        ("油性肌肤适用",),
        ("混合肌适用",),
    ],
)
def test_different_positive_skin_marker_is_insufficient_evidence(
    canonical_skin: tuple[str, ...],
) -> None:
    contracts = _contracts()
    request = contracts.ImageSuitabilityDecisionInput(
        reference=contracts.ImageSuitabilityDecisionReference(
            ordinal=1,
            image_id="image_" + "1" * 32,
            product_id=53,
        ),
        context=_resolved_context(skin_target="sensitive"),
        facts=_facts(suitable_skin=canonical_skin),
    )

    result = _subject().ImageSuitabilityDecisionFoundation().decide(request)

    assert result.status == "insufficient_evidence"
    assert result.reason == "canonical_skin_indeterminate"
    assert result.card_intent.visible_product_ids == (53,)


def test_audited_explicit_exclusion_is_not_suitable() -> None:
    contracts = _contracts()
    request = contracts.ImageSuitabilityDecisionInput(
        reference=contracts.ImageSuitabilityDecisionReference(
            ordinal=1,
            image_id="image_" + "1" * 32,
            product_id=53,
        ),
        context=_resolved_context(skin_target="sensitive"),
        facts=_facts(
            suitable_skin=("多种肤质适用（敏感肌除外）",),
        ),
    )

    result = _subject().ImageSuitabilityDecisionFoundation().decide(request)

    assert result.status == "not_suitable"
    assert result.reason == "canonical_skin_explicit_exclusion"
    assert result.card_intent.visible_product_ids == (53,)
    assert result.evidence_refs[-1] == "data/seed_dump.sql#product=53"


@pytest.mark.parametrize(
    "canonical_skin",
    [
        ("敏感性肤质不适用",),
        ("敏皮不适用",),
        ("敏感肌慎用",),
        ("不建议敏感肌使用",),
        ("避免敏感肌使用",),
        ("不推荐敏感肌使用",),
        ("敏感肌禁用",),
        ("敏感肌不宜使用",),
        ("敏感肌不可用",),
        ("敏感肌勿用",),
        ("not suitable for sensitive skin",),
        ("sensitive skin: use with caution",),
        ("not recommended for sensitive skin",),
        ("avoid use on sensitive skin",),
        ("should not be used on sensitive skin",),
        ("sensitive skin prohibited",),
        ("contraindicated for sensitive skin",),
    ],
)
def test_audited_target_negative_or_caution_is_not_suitable(
    canonical_skin: tuple[str, ...],
) -> None:
    result = _decide_for_skin_text(canonical_skin)

    assert result.status == "not_suitable"
    assert result.reason == "canonical_skin_explicit_exclusion"
    assert result.card_intent.visible_product_ids == (53,)


@pytest.mark.parametrize(
    "canonical_skin",
    [
        ("敏感肌适配性待确认",),
        ("敏感肌酌情使用",),
        ("并非不适合敏感肌",),
        ("不太适合敏感肌",),
        ("不一定适合敏感肌",),
        ("未必适合敏感肌",),
        ("敏感肌适用，但需慎用",),
        ("敏感肌适用性未知",),
        ("适合敏感肌，尚未确认",),
        ("sensitive skin suitability unverified",),
        ("possibly suitable for sensitive skin",),
        ("not proven unsuitable for sensitive skin",),
        ("not entirely suitable for sensitive skin",),
        ("not always suitable for sensitive skin",),
        ("suitable for sensitive skin, but use with caution",),
        ("suitable for sensitive skin pending confirmation",),
        ("recommended for sensitive skin, unverified",),
    ],
)
def test_ambiguous_target_wording_is_insufficient_evidence(
    canonical_skin: tuple[str, ...],
) -> None:
    result = _decide_for_skin_text(canonical_skin)

    assert result.status == "insufficient_evidence"
    assert result.reason == "canonical_skin_indeterminate"
    assert result.card_intent.visible_product_ids == (53,)


@pytest.mark.parametrize(
    "canonical_skin",
    [
        ("不怎么适合敏感肌",),
        ("不确定是否适合敏感肌",),
        ("非敏感肌适用",),
        ("适合于敏感肌",),
        ("推荐敏感肌",),
        ("not particularly suitable for sensitive skin",),
        ("hardly suitable for sensitive skin",),
        ("not known to be suitable for sensitive skin",),
    ],
)
def test_modified_positive_clause_is_insufficient_evidence(
    canonical_skin: tuple[str, ...],
) -> None:
    result = _decide_for_skin_text(canonical_skin)

    assert result.status == "insufficient_evidence"
    assert result.reason == "canonical_skin_indeterminate"


@pytest.mark.parametrize(
    "canonical_skin",
    [
        ("敏感肌适用",),
        ("适合敏感性肤质",),
        ("适用于敏感肌",),
        ("推荐给敏感肌",),
        ("可用于敏感肌",),
        ("敏皮可用",),
        ("敏感肌友好",),
        ("suitable for sensitive skin",),
        ("safe for sensitive skin",),
        ("appropriate for sensitive skin",),
        ("sensitive-skin friendly",),
        ("sensitive skin compatible",),
        ("recommended for sensitive skin",),
    ],
)
def test_conservative_target_positive_is_suitable(
    canonical_skin: tuple[str, ...],
) -> None:
    result = _decide_for_skin_text(canonical_skin)

    assert result.status == "suitable"
    assert result.reason == "canonical_skin_match"
    assert result.card_intent.visible_product_ids == (53,)


@pytest.mark.parametrize(
    ("canonical_skin", "own_target", "other_target"),
    [
        (("敏感肌",), "sensitive", "oily"),
        (("油性肤质",), "oily", "sensitive"),
        (("干皮",), "dry", "combination"),
        (("混合肌",), "combination", "normal"),
        (("混油皮",), "combination", "oily"),
        (("混油肤质",), "combination", "oily"),
        (("中性",), "normal", "dry"),
        (("油敏",), "oily_sensitive", "sensitive"),
        (("sensitive skin",), "sensitive", "normal"),
        (("oily skin",), "oily", "dry"),
    ],
)
def test_exact_bare_alias_is_positive_only_for_its_own_target(
    canonical_skin: tuple[str, ...],
    own_target: str,
    other_target: str,
) -> None:
    own_result = _decide_for_skin_text(
        canonical_skin,
        skin_target=own_target,
    )
    other_result = _decide_for_skin_text(
        canonical_skin,
        skin_target=other_target,
    )

    assert own_result.status == "suitable"
    assert own_result.reason == "canonical_skin_match"
    assert other_result.status == "insufficient_evidence"
    assert other_result.reason == "canonical_skin_indeterminate"


@pytest.mark.parametrize(
    ("product_id", "skin_target", "expected_skin"),
    [
        (45, "sensitive", ("敏感肌",)),
        (62, "oily", ("油性肤质",)),
        (79, "oily_sensitive", ("油皮", "混油皮", "混干皮", "敏感肌")),
        (83, "combination", ("混油皮",)),
        (113, "combination", ("油性肤质", "混油肤质")),
    ],
)
def test_real_canonical_bare_aliases_are_suitable_for_their_target(
    real_catalog: CanonicalGuideCatalog,
    product_id: int,
    skin_target: str,
    expected_skin: tuple[str, ...],
) -> None:
    facts = real_catalog.get_decision_facts(product_id)

    assert facts.suitable_skin == expected_skin
    assert facts.suitable_skin_source_refs

    result = _decide_for_facts(facts, skin_target=skin_target)

    assert result.status == "suitable"
    assert result.reason == "canonical_skin_match"
    assert result.evaluated_skin_fact.values == expected_skin
    assert result.evidence_refs[1:] == facts.suitable_skin_source_refs


@pytest.mark.parametrize(
    "canonical_skin",
    [
        ("超混油皮",),
        ("混油皮肤",),
        ("混油肤质状态",),
        ("适合混油皮肤",),
    ],
)
def test_combination_aliases_do_not_accept_substrings_or_near_matches(
    canonical_skin: tuple[str, ...],
) -> None:
    result = _decide_for_skin_text(
        canonical_skin,
        skin_target="combination",
    )

    assert result.status == "insufficient_evidence"
    assert result.reason == "canonical_skin_indeterminate"


@pytest.mark.parametrize(
    ("canonical_skin", "status", "reason"),
    [
        (
            ("混油皮不适用",),
            "not_suitable",
            "canonical_skin_explicit_exclusion",
        ),
        (
            ("混油肤质是否适用仍待确认",),
            "insufficient_evidence",
            "canonical_skin_indeterminate",
        ),
        (
            ("适合混油皮，不适合干皮",),
            "suitable",
            "canonical_skin_match",
        ),
    ],
)
def test_combination_aliases_preserve_clause_precedence(
    canonical_skin: tuple[str, ...],
    status: str,
    reason: str,
) -> None:
    result = _decide_for_skin_text(
        canonical_skin,
        skin_target="combination",
    )

    assert result.status == status
    assert result.reason == reason


@pytest.mark.parametrize(
    ("canonical_skin", "skin_target"),
    [
        (("适合敏感肌，不适合干皮",), "sensitive"),
        (("不适合干皮，适合敏感肌",), "sensitive"),
        (
            ("suitable for sensitive skin, not suitable for dry skin",),
            "sensitive",
        ),
        (
            ("not suitable for dry skin; suitable for sensitive skin",),
            "sensitive",
        ),
        (("适合干皮，不适合敏感肌",), "dry"),
        (
            ("not suitable for sensitive skin; suitable for dry skin",),
            "dry",
        ),
    ],
)
def test_selected_target_positive_survives_other_target_exclusion(
    canonical_skin: tuple[str, ...],
    skin_target: str,
) -> None:
    result = _decide_for_skin_text(
        canonical_skin,
        skin_target=skin_target,
    )

    assert result.status == "suitable"
    assert result.reason == "canonical_skin_match"


@pytest.mark.parametrize(
    "canonical_skin",
    [
        ("敏感肌适用，敏感肌不适用",),
        (
            "suitable for sensitive skin; "
            "not suitable for sensitive skin",
        ),
    ],
)
def test_later_same_target_explicit_negative_dominates_prior_positive(
    canonical_skin: tuple[str, ...],
) -> None:
    result = _decide_for_skin_text(canonical_skin)

    assert result.status == "not_suitable"
    assert result.reason == "canonical_skin_explicit_exclusion"


@pytest.mark.parametrize(
    "canonical_skin",
    [
        ("敏感肌适用", "敏感肌是否适用仍待确认"),
        ("敏感肌适用；敏感肌是否适用仍待确认",),
        (
            "suitable for sensitive skin",
            "whether suitable for sensitive skin remains unconfirmed",
        ),
        (
            "suitable for sensitive skin; "
            "suitability for sensitive skin remains uncertain",
        ),
    ],
)
def test_later_same_target_uncertainty_vetoes_prior_positive(
    canonical_skin: tuple[str, ...],
) -> None:
    result = _decide_for_skin_text(canonical_skin)

    assert result.status == "insufficient_evidence"
    assert result.reason == "canonical_skin_indeterminate"


@pytest.mark.parametrize(
    "canonical_skin",
    [
        ("敏感肌适用，极度敏感肌除外",),
        (
            "suitable for sensitive skin; "
            "except for extremely sensitive skin",
        ),
    ],
)
def test_narrow_target_exception_vetoes_positive_without_exact_exclusion(
    canonical_skin: tuple[str, ...],
) -> None:
    result = _decide_for_skin_text(canonical_skin)

    assert result.status == "insufficient_evidence"
    assert result.reason == "canonical_skin_indeterminate"


@pytest.mark.parametrize(
    "canonical_skin",
    [
        ("敏感肌适用，敏感肌除外",),
        (
            "suitable for sensitive skin; "
            "except for sensitive skin",
        ),
    ],
)
def test_exact_target_exception_remains_not_suitable(
    canonical_skin: tuple[str, ...],
) -> None:
    result = _decide_for_skin_text(canonical_skin)

    assert result.status == "not_suitable"
    assert result.reason == "canonical_skin_explicit_exclusion"


@pytest.mark.parametrize(
    "canonical_skin",
    [
        ("适合敏感肌但不适合干皮",),
        ("适合敏感肌但是不适合干皮",),
        ("适合敏感肌不过不适合干皮",),
        ("适合敏感肌然而不适合干皮",),
        ("suitable for sensitive skin but not suitable for dry skin",),
        ("suitable for sensitive skin however not suitable for dry skin",),
        ("suitable for sensitive skin while not suitable for dry skin",),
        ("suitable for sensitive skin whereas not suitable for dry skin",),
    ],
)
def test_contrast_conjunction_scopes_other_target_exclusion(
    canonical_skin: tuple[str, ...],
) -> None:
    result = _decide_for_skin_text(canonical_skin)

    assert result.status == "suitable"
    assert result.reason == "canonical_skin_match"


@pytest.mark.parametrize(
    "canonical_skin",
    [
        ("except sensitive skin",),
        ("except for sensitive skin",),
        ("suitable for all skin types except for sensitive skin",),
    ],
)
def test_targeted_english_exception_is_not_suitable(
    canonical_skin: tuple[str, ...],
) -> None:
    result = _decide_for_skin_text(canonical_skin)

    assert result.status == "not_suitable"
    assert result.reason == "canonical_skin_explicit_exclusion"


@pytest.mark.parametrize(
    "canonical_skin",
    [
        ("不适合干皮",),
        ("not suitable for dry skin",),
    ],
)
def test_other_target_exclusion_is_not_selected_target_exclusion(
    canonical_skin: tuple[str, ...],
) -> None:
    result = _decide_for_skin_text(
        canonical_skin,
        skin_target="sensitive",
    )

    assert result.status == "insufficient_evidence"
    assert result.reason == "canonical_skin_indeterminate"


@pytest.mark.parametrize(
    "canonical_skin",
    [
        ("适合油性肌肤",),
        ("干皮可用",),
        ("suitable for oily skin",),
        ("dry-skin friendly",),
    ],
)
def test_other_skin_positive_is_insufficient_for_sensitive_target(
    canonical_skin: tuple[str, ...],
) -> None:
    result = _decide_for_skin_text(canonical_skin)

    assert result.status == "insufficient_evidence"
    assert result.reason == "canonical_skin_indeterminate"


@pytest.mark.parametrize(
    ("state", "reason"),
    [
        (FactState.UNKNOWN, "canonical_skin_unknown"),
        (FactState.CONFLICT, "canonical_skin_conflict"),
    ],
)
def test_unknown_canonical_skin_fact_is_insufficient_not_a_safety_claim(
    state: FactState,
    reason: str,
) -> None:
    contracts = _contracts()
    request = contracts.ImageSuitabilityDecisionInput(
        reference=contracts.ImageSuitabilityDecisionReference(
            ordinal=1,
            image_id="image_" + "1" * 32,
            product_id=53,
        ),
        context=_resolved_context(),
        facts=_facts(
            suitable_skin=None,
            suitable_skin_state=state,
        ),
    )

    result = _subject().ImageSuitabilityDecisionFoundation().decide(request)

    assert result.status == "insufficient_evidence"
    assert result.reason == reason
    assert result.card_intent.visible_product_ids == (53,)
    assert result.status != "not_suitable"


def test_audited_not_applicable_skin_fact_is_not_suitable() -> None:
    contracts = _contracts()
    request = contracts.ImageSuitabilityDecisionInput(
        reference=contracts.ImageSuitabilityDecisionReference(
            ordinal=1,
            image_id="image_" + "1" * 32,
            product_id=53,
        ),
        context=_resolved_context(),
        facts=_facts(
            suitable_skin=None,
            suitable_skin_state=FactState.NOT_APPLICABLE,
        ),
    )

    result = _subject().ImageSuitabilityDecisionFoundation().decide(request)

    assert result.status == "not_suitable"
    assert result.reason == "canonical_skin_not_applicable"


def test_unaudited_not_applicable_skin_fact_is_insufficient() -> None:
    contracts = _contracts()
    request = contracts.ImageSuitabilityDecisionInput(
        reference=contracts.ImageSuitabilityDecisionReference(
            ordinal=1,
            image_id="image_" + "1" * 32,
            product_id=53,
        ),
        context=_resolved_context(),
        facts=_facts(
            suitable_skin=None,
            suitable_skin_state=FactState.NOT_APPLICABLE,
            source_refs=(),
        ),
    )

    result = _subject().ImageSuitabilityDecisionFoundation().decide(request)

    assert result.status == "insufficient_evidence"
    assert result.reason == "canonical_skin_unaudited"


def test_unaudited_known_skin_fact_is_insufficient() -> None:
    contracts = _contracts()
    request = contracts.ImageSuitabilityDecisionInput(
        reference=contracts.ImageSuitabilityDecisionReference(
            ordinal=1,
            image_id="image_" + "1" * 32,
            product_id=53,
        ),
        context=_resolved_context(),
        facts=_facts(source_refs=()),
    )

    result = _subject().ImageSuitabilityDecisionFoundation().decide(request)

    assert result.status == "insufficient_evidence"
    assert result.reason == "canonical_skin_unaudited"
    assert result.evidence_refs == ("turn:current#skin",)


@pytest.mark.parametrize(
    "source_ref",
    [
        "a" * 64,
        "0123456789abcdef" * 4,
        "data/seed_dump.sql#product=53",
    ],
)
def test_suitability_facts_accept_only_approved_canonical_ref_shapes(
    source_ref: str,
) -> None:
    contracts = _contracts()

    request = contracts.ImageSuitabilityDecisionInput(
        reference=contracts.ImageSuitabilityDecisionReference(
            ordinal=1,
            image_id="image_" + "1" * 32,
            product_id=53,
        ),
        context=_resolved_context(),
        facts=_facts(source_refs=(source_ref,)),
    )

    assert request.facts.suitable_skin_source_refs == (source_ref,)


@pytest.mark.parametrize(
    "source_ref",
    [
        "ocr:upload-1#suitable_skin",
        "user-upload:image-1#suitable_skin",
        "model:skin-classifier-v1",
        "canonical:53#suitable_skin",
        "A" * 64,
        "a" * 63,
        " " + "a" * 64,
        "data/seed_dump.sql#product=0",
        "data/seed_dump.sql#product=01",
        "data/seed_dump.sql#product=53 ",
        "data/seed_dump.sql#product=53:suitable_skin",
        "data/seed_dump.sql#product=54",
    ],
)
def test_suitability_facts_reject_noncanonical_or_mismatched_refs(
    source_ref: str,
) -> None:
    contracts = _contracts()

    with pytest.raises(
        ValidationError,
        match="Canonical suitability evidence",
    ):
        contracts.ImageSuitabilityDecisionInput(
            reference=contracts.ImageSuitabilityDecisionReference(
                ordinal=1,
                image_id="image_" + "1" * 32,
                product_id=53,
            ),
            context=_resolved_context(),
            facts=_facts(source_refs=(source_ref,)),
        )


def test_generic_canonical_skin_claim_is_insufficient() -> None:
    contracts = _contracts()
    request = contracts.ImageSuitabilityDecisionInput(
        reference=contracts.ImageSuitabilityDecisionReference(
            ordinal=1,
            image_id="image_" + "1" * 32,
            product_id=53,
        ),
        context=_resolved_context(),
        facts=_facts(suitable_skin=("全肤质适用",)),
    )

    result = _subject().ImageSuitabilityDecisionFoundation().decide(request)

    assert result.status == "insufficient_evidence"
    assert result.reason == "canonical_skin_indeterminate"


def test_context_claim_requires_exact_server_bound_provenance() -> None:
    contracts = _contracts()
    owner = ProfileOwnerRef(
        scope="local_demo",
        subject_id="profile_0123456789abcdef",
    )
    provenance = contracts.SuitabilityContextProvenance(
        current_bundle_id="bundle_" + "a" * 32,
        current_image_id="image_" + "1" * 32,
        session_id="session-current",
        conversation_version=7,
        source_kind=contracts.SuitabilityContextSource.LONG_TERM_PROFILE,
        evidence_ref="canonical-profile-fact:skin_type",
        profile_owner=owner,
        profile_version=3,
        profile_confirmed=True,
    )

    claim = contracts.SuitabilityContextClaim(
        skin_target="sensitive",
        provenance=provenance,
    )

    assert claim.provenance.current_bundle_id.startswith("bundle_")
    assert claim.provenance.current_image_id.startswith("image_")
    assert claim.provenance.session_id == "session-current"
    assert claim.provenance.conversation_version == 7
    assert claim.provenance.source_kind is (
        contracts.SuitabilityContextSource.LONG_TERM_PROFILE
    )
    assert claim.provenance.profile_owner == owner
    assert claim.provenance.profile_version == 3
    assert claim.provenance.profile_confirmed is True


def test_non_profile_context_forbids_profile_provenance() -> None:
    contracts = _contracts()

    with pytest.raises(ValidationError, match="profile provenance"):
        contracts.SuitabilityContextProvenance(
            current_bundle_id="bundle_" + "a" * 32,
            current_image_id="image_" + "1" * 32,
            session_id="session-current",
            conversation_version=7,
            source_kind=(
                contracts.SuitabilityContextSource.CURRENT_EXPLICIT_INPUT
            ),
            evidence_ref="turn-fact:skin_type",
            profile_owner=ProfileOwnerRef(
                scope="local_demo",
                subject_id="profile_0123456789abcdef",
            ),
            profile_version=3,
            profile_confirmed=True,
        )


def test_insufficient_reason_must_match_canonical_fact_state() -> None:
    contracts = _contracts()
    request = contracts.ImageSuitabilityDecisionInput(
        reference=contracts.ImageSuitabilityDecisionReference(
            ordinal=1,
            image_id="image_" + "1" * 32,
            product_id=53,
        ),
        context=_resolved_context(),
        facts=_facts(
            suitable_skin=None,
            suitable_skin_state=FactState.UNKNOWN,
        ),
    )
    result = _subject().ImageSuitabilityDecisionFoundation().decide(request)
    payload = result.model_dump()
    payload["reason"] = "canonical_skin_unaudited"

    with pytest.raises(ValidationError, match="reason"):
        contracts.ImageSuitabilityDecisionResult.model_validate(payload)
