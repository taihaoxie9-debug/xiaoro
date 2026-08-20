from __future__ import annotations

from app.guide.retrieval.category_fact_contracts import (
    AuthorizedCategoryFact,
    SourceClass,
)
from app.guide.retrieval.category_profiles import CategoryProfile
from app.guide.retrieval.merchant_claim_assets import (
    MerchantClaim,
    merchant_claim_id,
)
from app.guide.retrieval.product_evidence_assets import (
    ProductEvidenceBlock,
    product_evidence_id,
)
from app.guide.retrieval.selection_fact_reader import SelectionFactReader


class _Reader:
    def __init__(self, rows: tuple[object, ...]) -> None:
        self._rows = rows

    def read(self, *, product_id: int, **_: object) -> tuple[object, ...]:
        return tuple(
            row
            for row in self._rows
            if getattr(row, "product_id", product_id) == product_id
        )


def _base_fact() -> AuthorizedCategoryFact:
    return AuthorizedCategoryFact(
        category_profile=CategoryProfile.SKINCARE,
        field_key="efficacy",
        value=("保湿",),
        resolved_state="known",
        source_classes=(SourceClass.STRUCTURED_OFFICIAL,),
        source_refs=("official:hydrating",),
        capabilities={
            "evidence",
            "display",
            "compare",
            "hard_filter",
            "soft_rank",
        },
    )


def _claim(
    *,
    claim_id_seed: str,
    value: str = "保湿",
    field_key: str = "efficacy",
    profile: CategoryProfile = CategoryProfile.SKINCARE,
) -> MerchantClaim:
    payload = {
        "product_id": 78,
        "category_profile": profile.value,
        "field_key": field_key,
        "normalized_value": value,
        "display_claim": f"商家称{value}",
        "claim_scope": "ordinary",
        "source_class": "merchant_description_ocr",
        "source_sha256": claim_id_seed * 64,
        "record_sha256": claim_id_seed * 64,
        "source_locator": (
            "urn:xiaoro:merchant-description-ocr:pid:78:"
            f"source-sha256:{claim_id_seed * 64}:"
            f"record-sha256:{claim_id_seed * 64}"
        ),
        "review_source_sha256": "f" * 64,
        "review_rationale": "人工审核普通功效宣传。",
        "capabilities": [
            "evidence",
            "display",
            "compare",
            "soft_rank",
        ],
    }
    return MerchantClaim.model_validate(
        {
            "claim_id": merchant_claim_id(payload),
            **payload,
        },
        strict=True,
    )


def _evidence(
    *,
    value: str = "保湿",
    subject_scope: str = "exact_product",
    variant_scope: str | None = None,
    exact_text: str | None = None,
    descriptors: list[str] | None = None,
    relations: list[dict[str, str]] | None = None,
) -> ProductEvidenceBlock:
    source = {
        "source_file": "detail_78_ocr.json",
        "source_sha256": "a" * 64,
        "image_file": "001.jpg",
        "image_index": 1,
        "image_sha256": "b" * 64,
        "source_locator": (
            "urn:xiaoro:product-detail-image:pid:78:"
            f"source-sha256:{'a' * 64}:image-sha256:{'b' * 64}"
        ),
        "source_url": "https://example.com/001.jpg",
        "recovery_status": "source_record",
        "resolved_image_file": "001.jpg",
        "image_region": [0, 0, 790, 1000],
    }
    payload = {
        "product_id": 78,
        "subject_scope": subject_scope,
        "variant_scope": variant_scope,
        "management_label": "merchant_cited_test",
        "transcription_basis": "visual_transcription",
        "exact_text": exact_text or f"产品级测试支持{value}",
        "plain_meaning": f"测试支持{value}",
        "relations": relations or [],
        "qualifiers": {
            "sample_size": 35,
            "population": None,
            "method": "第三方仪器测试",
            "baseline": None,
            "duration": None,
            "disclaimer": None,
            "footnotes": [],
        },
        "free_descriptors": descriptors or [value],
        "review_status": "accepted",
        "allowed_uses": [
            "answer",
            "compare",
            "display",
            "soft_rank",
        ],
        "forbidden_uses": ["hard_filter", "safety_guarantee"],
        "review_rationale": "原图与样本脚注清晰。",
        "selection_review": {
            "decision": "projected",
            "visual_confirmed": True,
            "rationale": "产品级测试可正常软排。",
            "projections": [
                {
                    "field_key": "efficacy",
                    "normalized_value": value,
                    "capabilities": ["compare", "soft_rank"],
                    "rank_strength": 2,
                    "safety_role": "ordinary",
                }
            ],
        },
        "source": source,
    }
    return ProductEvidenceBlock.model_validate(
        {
            "evidence_id": product_evidence_id(payload),
            **payload,
        },
        strict=True,
    )


def _reader(
    *,
    claims: tuple[MerchantClaim, ...],
    evidence: tuple[ProductEvidenceBlock, ...],
) -> SelectionFactReader:
    return SelectionFactReader(
        base=_Reader((_base_fact(),)),
        claims=_Reader(claims),
        evidence=_Reader(evidence),
    )


def test_reader_deduplicates_sources_and_uses_maximum_strength() -> None:
    claim = _claim(claim_id_seed="c")
    block = _evidence()

    facts = _reader(
        claims=(claim,),
        evidence=(block,),
    ).read(
        product_id=78,
        profile=CategoryProfile.SKINCARE,
    )

    assert len(facts) == 1
    assert facts[0].normalized_value == "保湿"
    assert facts[0].rank_strength == 2
    assert facts[0].source_refs == (
        block.evidence_id,
        "official:hydrating",
        claim.source_locator,
    )


def test_reader_projects_unique_visually_confirmed_card_specification() -> None:
    block = _evidence(
        exact_text="测试精华30ml，主打保湿",
        descriptors=["测试精华30ml", "保湿"],
        relations=[
            {
                "subject": "测试精华30ml",
                "predicate": "merchant_positions_for",
                "object": "保湿",
            }
        ],
    )

    facts = _reader(
        claims=(),
        evidence=(block,),
    ).read(
        product_id=78,
        profile=CategoryProfile.SKINCARE,
    )

    specification = next(
        item for item in facts if item.field_key == "net_content"
    )
    assert specification.normalized_value == "30ml"
    assert specification.capabilities == frozenset({"compare"})
    assert specification.source_refs == (block.evidence_id,)
    assert block.evidence_id == product_evidence_id(
        block.model_dump(mode="json", exclude={"evidence_id"})
    )


def test_reader_does_not_project_bundle_quantity_as_single_specification() -> None:
    block = _evidence(
        exact_text="测试精华30ml×2组合",
        descriptors=["测试精华30ml×2"],
        relations=[
            {
                "subject": "测试精华30ml×2",
                "predicate": "merchant_bundle_specification",
                "object": "双瓶组合",
            }
        ],
    )

    facts = _reader(
        claims=(),
        evidence=(block,),
    ).read(
        product_id=78,
        profile=CategoryProfile.SKINCARE,
    )

    assert all(item.field_key != "net_content" for item in facts)


def test_repeated_claims_remain_one_selection_fact() -> None:
    facts = _reader(
        claims=(
            _claim(claim_id_seed="c"),
            _claim(claim_id_seed="d"),
        ),
        evidence=(),
    ).read(
        product_id=78,
        profile=CategoryProfile.SKINCARE,
    )

    assert len(facts) == 1
    assert facts[0].rank_strength == 2
    assert len(facts[0].source_refs) == 3


def test_distinct_value_and_variant_scope_remain_separate() -> None:
    facts = _reader(
        claims=(_claim(claim_id_seed="c", value="舒缓"),),
        evidence=(
            _evidence(
                value="保湿",
                subject_scope="exact_variant",
                variant_scope="6片装",
            ),
        ),
    ).read(
        product_id=78,
        profile=CategoryProfile.SKINCARE,
    )

    assert {
        (
            item.normalized_value,
            item.subject_scope,
            item.variant_scope,
        )
        for item in facts
    } == {
        ("保湿", "exact_product", None),
        ("保湿", "exact_variant", "6片装"),
        ("舒缓", "exact_product", None),
    }


def test_profile_inapplicable_claim_is_rejected_not_hidden() -> None:
    reader = _reader(
        claims=(
            _claim(
                claim_id_seed="c",
                field_key="spf_pa",
                value="SPF50+ / PA++++",
            ),
        ),
        evidence=(),
    )

    try:
        reader.read(
            product_id=78,
            profile=CategoryProfile.SKINCARE,
        )
    except ValueError as exc:
        assert "not applicable to category profile" in str(exc)
    else:
        raise AssertionError(
            "profile-inapplicable selection claim was silently dropped"
        )
