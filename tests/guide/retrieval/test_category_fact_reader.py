from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.guide.decision.contracts import DecisionProductFacts, FactState
from app.guide.presentation.contracts import ProductCardFacts
from app.guide.retrieval.category_fact_assets import (
    PILOT_BINDINGS,
    ApprovedCategoryFact,
    CategoryFactAssets,
    CategoryFactManifest,
)
from app.guide.retrieval.category_fact_contracts import (
    AuthorizedCategoryFact,
    SourceClass,
    category_field_registry,
    filter_category_facts_by_capability,
)
from app.guide.retrieval.category_fact_reader import (
    CategoryFactReaderIntegrityError,
    CategoryFactProfileMismatchError,
    CategoryFactReader,
)
from app.guide.retrieval.category_profiles import CategoryProfile


def _manifest(*, fact_count: int) -> CategoryFactManifest:
    return CategoryFactManifest(
        asset_id="task9-reader-fixture",
        asset_version=(
            "approved-category-facts-v1:sha256:" + "1" * 64
        ),
        fact_count=fact_count,
        facts_file="approved.jsonl",
        facts_sha256="1" * 64,
        manifest_sha256="2" * 64,
        pilot_bindings=PILOT_BINDINGS,
        schema_version="approved-category-facts-v1",
    )


def _approved_fact(
    *,
    fact_id: str,
    field_key: str,
    value,
    source_class: SourceClass,
    source_ref: str,
    source_sha256: str,
) -> ApprovedCategoryFact:
    return ApprovedCategoryFact(
        fact_id=fact_id,
        product_id=79,
        category_profile=CategoryProfile.BASE_MAKEUP,
        field_key=field_key,
        value=value,
        source_class=source_class,
        source_refs=(source_ref,),
        source_sha256=source_sha256,
        reviewer="task9-reviewer",
        reviewed_at=datetime(2026, 8, 10, tzinfo=UTC),
    )


def _reader(
    facts: tuple[ApprovedCategoryFact, ...] = (),
) -> CategoryFactReader:
    return CategoryFactReader(
        assets=CategoryFactAssets(
            manifest=_manifest(fact_count=len(facts)),
            facts=facts,
        ),
        field_registry=category_field_registry(),
    )


def _reader_assets(
    *,
    facts: tuple[object, ...] = (),
    manifest: object | None = None,
) -> CategoryFactAssets:
    return CategoryFactAssets(
        manifest=(
            manifest
            if manifest is not None
            else _manifest(fact_count=len(facts))
        ),
        facts=facts,
    )


def _model_construct_fact(**updates) -> ApprovedCategoryFact:
    fact = _approved_fact(
        fact_id="9" * 64,
        field_key="shade",
        value=["1C0"],
        source_class=SourceClass.STRUCTURED_OFFICIAL,
        source_ref="urn:task9:model-construct",
        source_sha256="9" * 64,
    )
    payload = fact.model_dump(mode="python")
    payload.update(updates)
    return ApprovedCategoryFact.model_construct(**payload)


def test_authorized_category_fact_binds_to_registry_profile() -> None:
    fact = AuthorizedCategoryFact(
        category_profile=CategoryProfile.BASE_MAKEUP,
        field_key="shade",
        value=("1C0", "2C0"),
        resolved_state="known",
        source_classes=(SourceClass.STRUCTURED_OFFICIAL,),
        source_refs=("urn:task9:shade",),
        capabilities=frozenset({"evidence", "display", "compare"}),
    )

    assert fact.category_profile is CategoryProfile.BASE_MAKEUP


@pytest.mark.parametrize(
    ("category_profile", "field_key", "expected_error"),
    (
        (
            CategoryProfile.BASE_MAKEUP,
            "product_identity",
            "canonical core",
        ),
        (
            CategoryProfile.BASE_MAKEUP,
            "unregistered_field",
            "unknown category fact field",
        ),
        (
            CategoryProfile.BASE_MAKEUP,
            "fragrance_family",
            "not applicable",
        ),
    ),
)
def test_authorized_category_fact_rejects_registry_field_mismatch(
    category_profile: CategoryProfile,
    field_key: str,
    expected_error: str,
) -> None:
    with pytest.raises(ValidationError, match=expected_error):
        AuthorizedCategoryFact(
            category_profile=category_profile,
            field_key=field_key,
            value=("woody",),
            resolved_state="known",
            source_classes=(SourceClass.STRUCTURED_OFFICIAL,),
            source_refs=("urn:task9:registry-field",),
            capabilities=frozenset({"evidence", "display"}),
        )


def test_authorized_category_fact_rejects_unapproved_source_class() -> None:
    with pytest.raises(ValidationError, match="source is not authorized"):
        AuthorizedCategoryFact(
            category_profile=CategoryProfile.SUNCARE,
            field_key="spf_pa",
            value="SPF50+ / PA++++",
            resolved_state="known",
            source_classes=(SourceClass.APPROVED_CONSUMER_REVIEW,),
            source_refs=("urn:task9:unapproved-source",),
            capabilities=frozenset({"evidence"}),
        )


def test_official_description_cannot_self_authorize_filter_or_rank() -> None:
    with pytest.raises(ValidationError, match="capabilities exceed"):
        AuthorizedCategoryFact(
            category_profile=CategoryProfile.BASE_MAKEUP,
            field_key="longevity",
            value="8 hours",
            resolved_state="known",
            source_classes=(SourceClass.OFFICIAL_DESCRIPTION,),
            source_refs=("urn:task9:capability-escalation",),
            capabilities=frozenset(
                {"evidence", "display", "hard_filter", "soft_rank"}
            ),
        )


@pytest.mark.parametrize(
    ("field_key", "value"),
    (
        ("shade", True),
        ("longevity", ("8 hours",)),
        ("double_cleanse", "true"),
    ),
)
def test_authorized_category_fact_enforces_registry_value_type(
    field_key: str,
    value,
) -> None:
    profile = (
        CategoryProfile.CLEANSER
        if field_key == "double_cleanse"
        else CategoryProfile.BASE_MAKEUP
    )
    with pytest.raises(ValidationError, match="value type mismatch"):
        AuthorizedCategoryFact(
            category_profile=profile,
            field_key=field_key,
            value=value,
            resolved_state="known",
            source_classes=(SourceClass.STRUCTURED_OFFICIAL,),
            source_refs=("urn:task9:value-type",),
            capabilities=frozenset({"evidence", "display"}),
        )


def test_authorized_string_list_requires_strict_tuple() -> None:
    with pytest.raises(ValidationError, match="strict tuple"):
        AuthorizedCategoryFact(
            category_profile=CategoryProfile.BASE_MAKEUP,
            field_key="shade",
            value=["1C0"],
            resolved_state="known",
            source_classes=(SourceClass.STRUCTURED_OFFICIAL,),
            source_refs=("urn:task9:strict-tuple",),
            capabilities=frozenset({"evidence", "display"}),
        )


@pytest.mark.parametrize(
    "contract",
    ("decision", "presentation"),
)
def test_product_fact_contract_rejects_wrong_profile_category_fact(
    contract: str,
) -> None:
    wrong_profile = AuthorizedCategoryFact.model_construct(
        category_profile=CategoryProfile.FRAGRANCE,
        field_key="fragrance_family",
        value=("woody",),
        resolved_state="known",
        source_classes=(SourceClass.STRUCTURED_OFFICIAL,),
        source_refs=("urn:task9:wrong-profile",),
        capabilities=frozenset({"evidence", "display"}),
    )

    with pytest.raises(ValidationError, match="category fact profile"):
        if contract == "decision":
            DecisionProductFacts(
                product_id=79,
                category_profile=CategoryProfile.BASE_MAKEUP,
                category_fields=(wrong_profile,),
                price=None,
                price_state=FactState.UNKNOWN,
                efficacy=None,
                efficacy_state=FactState.UNKNOWN,
                suitable_skin=None,
                suitable_skin_state=FactState.UNKNOWN,
                ingredients_present=None,
                ingredients_present_state=FactState.UNKNOWN,
                verified_absences=None,
                verified_absences_state=FactState.UNKNOWN,
            )
        else:
            ProductCardFacts(
                product_id=79,
                category_profile=CategoryProfile.BASE_MAKEUP,
                category_fields=(wrong_profile,),
                name="probe",
                brand="probe",
                category="粉底液",
                price=None,
                fact_warnings=[],
            )


def test_capability_filter_revalidates_model_construct_facts() -> None:
    malformed = AuthorizedCategoryFact.model_construct(
        category_profile=CategoryProfile.SUNCARE,
        field_key="water_resistance",
        value="marketing claim",
        resolved_state="known",
        source_classes=(SourceClass.OFFICIAL_DESCRIPTION,),
        source_refs=("urn:task9:filter-revalidation",),
        capabilities=frozenset({"evidence", "hard_filter", "soft_rank"}),
    )

    with pytest.raises(ValidationError, match="capabilities exceed"):
        filter_category_facts_by_capability((malformed,), "hard_filter")


def test_capability_filter_rejects_model_construct_missing_fields() -> None:
    malformed = AuthorizedCategoryFact.model_construct(
        category_profile=CategoryProfile.SUNCARE,
        field_key="water_resistance",
        resolved_state="known",
        source_classes=(SourceClass.STRUCTURED_OFFICIAL,),
        source_refs=("urn:task9:filter-missing-value",),
        capabilities=frozenset({"evidence"}),
    )

    with pytest.raises(ValidationError):
        filter_category_facts_by_capability((malformed,), "evidence")


def test_reader_rejects_duck_typed_assets() -> None:
    assets = SimpleNamespace(
        manifest=_manifest(fact_count=0),
        facts=(),
    )

    with pytest.raises(
        CategoryFactReaderIntegrityError,
        match="CategoryFactAssets",
    ):
        CategoryFactReader(
            assets=assets,
            field_registry=category_field_registry(),
        )


def test_reader_rejects_duck_typed_manifest() -> None:
    manifest = SimpleNamespace(
        fact_count=0,
        pilot_bindings=PILOT_BINDINGS,
    )

    with pytest.raises(
        CategoryFactReaderIntegrityError,
        match="CategoryFactManifest",
    ):
        CategoryFactReader(
            assets=_reader_assets(manifest=manifest),
            field_registry=category_field_registry(),
        )


@pytest.mark.parametrize("evidence_status", ("pending", "quarantine"))
def test_reader_rejects_pending_and_quarantine_duck_facts(
    evidence_status: str,
) -> None:
    payload = _model_construct_fact(
        evidence_status=evidence_status,
    ).model_dump(mode="python")
    duck_fact = SimpleNamespace(**payload)

    with pytest.raises(
        CategoryFactReaderIntegrityError,
        match="ApprovedCategoryFact",
    ):
        CategoryFactReader(
            assets=_reader_assets(facts=(duck_fact,)),
            field_registry=category_field_registry(),
        )


@pytest.mark.parametrize("evidence_status", ("pending", "quarantine"))
def test_reader_rejects_non_approved_model_construct_facts(
    evidence_status: str,
) -> None:
    fact = _model_construct_fact(evidence_status=evidence_status)

    with pytest.raises(
        CategoryFactReaderIntegrityError,
        match="evidence_status",
    ):
        CategoryFactReader(
            assets=_reader_assets(facts=(fact,)),
            field_registry=category_field_registry(),
        )


@pytest.mark.parametrize(
    "updates",
    (
        {"value": True},
        {"category_profile": "base_makeup"},
        {"source_class": "structured_official"},
        {"source_refs": ["urn:task9:model-construct"]},
        {"source_refs": ()},
    ),
)
def test_reader_revalidates_model_construct_approved_fact_fields(
    updates: dict[str, object],
) -> None:
    fact = _model_construct_fact(**updates)

    with pytest.raises(
        CategoryFactReaderIntegrityError,
        match="invalid approved category fact",
    ):
        CategoryFactReader(
            assets=_reader_assets(facts=(fact,)),
            field_registry=category_field_registry(),
        )


def test_reader_rejects_model_construct_fact_with_missing_fields() -> None:
    fact = ApprovedCategoryFact.model_construct(
        fact_id="8" * 64,
        product_id=79,
        category_profile=CategoryProfile.BASE_MAKEUP,
        field_key="shade",
        value=["1C0"],
        source_class=SourceClass.STRUCTURED_OFFICIAL,
        source_refs=("urn:task9:missing-review",),
        source_sha256="8" * 64,
        evidence_status="approved_fact",
    )

    with pytest.raises(
        CategoryFactReaderIntegrityError,
        match="invalid approved category fact",
    ):
        CategoryFactReader(
            assets=_reader_assets(facts=(fact,)),
            field_registry=category_field_registry(),
        )


def test_reader_rejects_manifest_fact_count_mismatch() -> None:
    fact = _model_construct_fact()

    with pytest.raises(
        CategoryFactReaderIntegrityError,
        match="fact_count",
    ):
        CategoryFactReader(
            assets=_reader_assets(
                facts=(fact,),
                manifest=_manifest(fact_count=0),
            ),
            field_registry=category_field_registry(),
        )


def test_reader_rejects_non_integer_manifest_fact_count() -> None:
    valid_manifest = _manifest(fact_count=1)
    manifest = CategoryFactManifest.model_construct(
        **{
            field_name: getattr(valid_manifest, field_name)
            for field_name in CategoryFactManifest.model_fields
            if field_name != "fact_count"
        },
        **{
            "fact_count": True,
        },
    )

    with pytest.raises(
        CategoryFactReaderIntegrityError,
        match="fact_count",
    ):
        CategoryFactReader(
            assets=_reader_assets(
                facts=(_model_construct_fact(),),
                manifest=manifest,
            ),
            field_registry=category_field_registry(),
        )


def test_authorized_category_fact_is_strict_frozen_and_typed() -> None:
    fact = AuthorizedCategoryFact(
        category_profile=CategoryProfile.BASE_MAKEUP,
        field_key="shade",
        value=("1C0", "2C0"),
        resolved_state="known",
        source_classes=(SourceClass.STRUCTURED_OFFICIAL,),
        source_refs=("urn:task9:shade",),
        capabilities=frozenset({"evidence", "display", "compare"}),
    )

    assert fact.value == ("1C0", "2C0")
    with pytest.raises(ValidationError):
        fact.field_key = "finish"
    with pytest.raises(ValidationError):
        AuthorizedCategoryFact(
            category_profile=CategoryProfile.BASE_MAKEUP,
            field_key="shade",
            value={"unsafe": "dictionary"},
            resolved_state="known",
            source_classes=(SourceClass.STRUCTURED_OFFICIAL,),
            source_refs=("urn:task9:shade",),
            capabilities=frozenset({"evidence", "display"}),
        )


@pytest.mark.parametrize(
    "state",
    ("unknown", "conflict", "not_applicable"),
)
def test_non_known_category_fact_forbids_values_and_public_capabilities(
    state: str,
) -> None:
    with pytest.raises(ValidationError):
        AuthorizedCategoryFact(
            category_profile=CategoryProfile.BASE_MAKEUP,
            field_key="shade",
            value="1C0",
            resolved_state=state,
            source_classes=(SourceClass.UNKNOWN,),
            source_refs=(),
            capabilities=frozenset({"evidence"}),
        )
    with pytest.raises(ValidationError):
        AuthorizedCategoryFact(
            category_profile=CategoryProfile.BASE_MAKEUP,
            field_key="shade",
            value=None,
            resolved_state=state,
            source_classes=(SourceClass.UNKNOWN,),
            source_refs=(),
            capabilities=frozenset({"evidence", "display"}),
        )


def test_capability_filter_only_returns_existing_authorized_known_facts() -> None:
    display_only = AuthorizedCategoryFact(
        category_profile=CategoryProfile.BASE_MAKEUP,
        field_key="longevity",
        value="8 hours",
        resolved_state="known",
        source_classes=(SourceClass.OFFICIAL_DESCRIPTION,),
        source_refs=("urn:task9:longevity",),
        capabilities=frozenset({"evidence", "display"}),
    )
    compare_safe = AuthorizedCategoryFact(
        category_profile=CategoryProfile.BASE_MAKEUP,
        field_key="shade",
        value=("1C0",),
        resolved_state="known",
        source_classes=(SourceClass.STRUCTURED_OFFICIAL,),
        source_refs=("urn:task9:shade",),
        capabilities=frozenset({"evidence", "display", "compare"}),
    )
    unknown = AuthorizedCategoryFact(
        category_profile=CategoryProfile.BASE_MAKEUP,
        field_key="finish",
        value=None,
        resolved_state="unknown",
        source_classes=(SourceClass.UNKNOWN,),
        source_refs=(),
        capabilities=frozenset({"evidence"}),
    )
    facts = (display_only, compare_safe, unknown)

    assert filter_category_facts_by_capability(
        facts,
        "compare",
    ) == (compare_safe,)
    assert filter_category_facts_by_capability(
        facts,
        "hard_filter",
    ) == ()
    assert all(
        fact in facts
        for fact in filter_category_facts_by_capability(facts, "display")
    )


def test_empty_asset_generates_unknown_for_each_applicable_non_core_field() -> None:
    values = _reader().read(
        product_id=79,
        profile=CategoryProfile.BASE_MAKEUP,
    )

    assert tuple(item.field_key for item in values) == tuple(
        sorted(item.field_key for item in values)
    )
    assert {item.field_key for item in values} == {
        "application_area",
        "coverage",
        "efficacy",
        "finish",
        "claimed_absences",
        "claimed_ingredients",
        "ingredients_present",
        "longevity",
        "makeup_effect",
        "mechanism",
        "net_content",
        "origin",
        "product_form",
        "safety",
        "shade",
        "shelf_life",
        "skin_concern",
        "spf_pa",
        "suitable_skin",
        "sun_protection_claim",
        "target_audience",
        "texture",
        "usage",
        "usage_context",
        "variant_option",
        "verified_absences",
    }
    assert all(item.resolved_state == "unknown" for item in values)
    assert all(item.value is None for item in values)
    assert all(item.capabilities == frozenset({"evidence"}) for item in values)


def test_reader_merges_equal_provenance_and_neutralizes_conflicts() -> None:
    facts = (
        _approved_fact(
            fact_id="1" * 64,
            field_key="longevity",
            value="8 hours",
            source_class=SourceClass.STRUCTURED_OFFICIAL,
            source_ref="urn:task9:longevity:structured",
            source_sha256="a" * 64,
        ),
        _approved_fact(
            fact_id="2" * 64,
            field_key="longevity",
            value="8 hours",
            source_class=SourceClass.OFFICIAL_DESCRIPTION,
            source_ref="urn:task9:longevity:description",
            source_sha256="b" * 64,
        ),
        _approved_fact(
            fact_id="3" * 64,
            field_key="coverage",
            value="medium",
            source_class=SourceClass.STRUCTURED_OFFICIAL,
            source_ref="urn:task9:coverage:medium",
            source_sha256="c" * 64,
        ),
        _approved_fact(
            fact_id="4" * 64,
            field_key="coverage",
            value="full",
            source_class=SourceClass.OFFICIAL_PACKAGING,
            source_ref="urn:task9:coverage:full",
            source_sha256="d" * 64,
        ),
    )

    values = {
        item.field_key: item
        for item in _reader(facts).read(
            product_id=79,
            profile=CategoryProfile.BASE_MAKEUP,
        )
    }

    longevity = values["longevity"]
    assert longevity.value == "8 hours"
    assert longevity.source_refs == (
        "urn:task9:longevity:description",
        "urn:task9:longevity:structured",
    )
    assert longevity.source_classes == (
        SourceClass.OFFICIAL_DESCRIPTION,
        SourceClass.STRUCTURED_OFFICIAL,
    )
    assert longevity.capabilities == frozenset({"evidence", "display"})

    coverage = values["coverage"]
    assert coverage.resolved_state == "conflict"
    assert coverage.value is None
    assert coverage.capabilities == frozenset({"evidence"})
    assert coverage.source_refs == (
        "urn:task9:coverage:full",
        "urn:task9:coverage:medium",
    )


def test_reader_returns_only_current_profile_non_core_fields() -> None:
    values = _reader().read(
        product_id=79,
        profile=CategoryProfile.BASE_MAKEUP,
    )

    forbidden = {
        "product_identity",
        "brand",
        "category",
        "price",
        "fragrance_family",
    }
    assert forbidden.isdisjoint(item.field_key for item in values)


@pytest.mark.parametrize(
    ("field_key", "value", "expected_error"),
    (
        (
            "fragrance_family",
            ["woody"],
            "not applicable",
        ),
        (
            "product_identity",
            "forged identity",
            "canonical core",
        ),
    ),
)
def test_reader_rejects_assets_outside_profile_sidecar_authority(
    field_key: str,
    value,
    expected_error: str,
) -> None:
    fact = _approved_fact(
        fact_id="f" * 64,
        field_key=field_key,
        value=value,
        source_class=SourceClass.STRUCTURED_OFFICIAL,
        source_ref=f"urn:task9:forbidden:{field_key}",
        source_sha256="e" * 64,
    )

    with pytest.raises(
        CategoryFactReaderIntegrityError,
        match=expected_error,
    ):
        _reader((fact,))


def test_known_product_profile_mismatch_fails_closed() -> None:
    with pytest.raises(
        CategoryFactProfileMismatchError,
        match="product=79",
    ):
        _reader().read(
            product_id=79,
            profile=CategoryProfile.FRAGRANCE,
        )
