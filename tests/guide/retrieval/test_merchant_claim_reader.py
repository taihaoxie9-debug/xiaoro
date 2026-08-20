from __future__ import annotations

import json
from pathlib import Path

from app.guide.retrieval.category_fact_contracts import (
    category_field_registry,
)
from app.guide.retrieval.category_fact_reader import (
    EmptyCategoryFactReader,
)
from app.guide.retrieval.category_profiles import CategoryProfile
from app.guide.retrieval.merchant_claim_assets import (
    load_merchant_claim_assets,
)
from app.guide.retrieval.merchant_claim_reader import (
    ClaimAugmentedCategoryFactReader,
    MerchantClaimReader,
)
from tools.guide_data.build_ocr_merchant_claims import (
    build_ocr_merchant_claims,
)


def _claim_reader(tmp_path: Path) -> MerchantClaimReader:
    source_root = tmp_path / "ocr"
    source_root.mkdir()
    (source_root / "detail_55_ocr.json").write_text(
        json.dumps(
            {
                "pid": 55,
                "name": "测试防晒",
                "images": [
                    {
                        "file": "claim.jpg",
                        "size": [100, 200],
                        "size_kb": 12.0,
                        "ocr_text": (
                            "油皮亲妈 清爽不黏腻 "
                            "敏感肌适用 无酒精 孕妇可用"
                        ),
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    review_path = tmp_path / "review.jsonl"
    review_rows = [
        ("suitable_skin", "油性", "油皮亲妈", "ordinary"),
        ("suitable_skin", "敏感", "敏感肌适用", "ordinary"),
        ("texture", "清爽", "清爽不黏腻", "ordinary"),
        ("safety_claim", "不含酒精", "无酒精", "safety_transcript"),
        ("safety_claim", "孕妇可用", "孕妇可用", "safety_transcript"),
    ]
    review_path.write_text(
        "\n".join(
            json.dumps(
                {
                    "product_id": 55,
                    "field_key": field_key,
                    "normalized_value": normalized,
                    "display_claim": display,
                    "claim_scope": scope,
                    "source_file": "detail_55_ocr.json",
                    "image_file": "claim.jpg",
                    "image_index": 0,
                    "rationale": "品类审查候选",
                },
                ensure_ascii=False,
                sort_keys=True,
            )
            for field_key, normalized, display, scope in review_rows
        ),
        encoding="utf-8",
    )
    built = build_ocr_merchant_claims(
        source_root=source_root,
        review_paths=(review_path,),
        output_root=tmp_path / "out",
        product_profiles={55: CategoryProfile.SUNCARE},
    )
    return MerchantClaimReader(
        load_merchant_claim_assets(
            manifest_path=built.manifest_path,
            claims_path=built.claims_path,
        )
    )


def test_claim_reader_keeps_display_text_and_projects_only_ordinary_rank(
    tmp_path: Path,
) -> None:
    claims = _claim_reader(tmp_path)
    registry = category_field_registry()
    facts = ClaimAugmentedCategoryFactReader(
        base=EmptyCategoryFactReader(registry),
        claims=claims,
        field_registry=registry,
    ).read(product_id=55, profile=CategoryProfile.SUNCARE)

    by_key = {fact.field_key: fact for fact in facts}
    assert by_key["texture"].value == ("清爽",)
    assert set(by_key["suitable_skin"].value) == {"油性", "敏感"}
    assert by_key["texture"].resolved_state == "known"
    assert by_key["texture"].capabilities == frozenset(
        {"evidence", "display", "compare", "soft_rank"}
    )
    assert "hard_filter" not in by_key["suitable_skin"].capabilities
    assert "safety_claim" not in by_key

    display = claims.read(product_id=55)
    assert any(
        claim.display_claim == "清爽不黏腻"
        and claim.normalized_value == "清爽"
        for claim in display
    )
    assert any(
        claim.claim_scope == "safety_transcript"
        and claim.display_claim in {"无酒精", "孕妇可用"}
        and "soft_rank" not in claim.capabilities
        for claim in display
    )
