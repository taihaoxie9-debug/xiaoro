from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from app.guide.retrieval.category_profiles import CategoryProfile
from app.guide.retrieval.merchant_claim_assets import (
    load_merchant_claim_assets,
)
from tools.guide_data.build_ocr_merchant_claims import (
    OcrMerchantClaimBuildError,
    build_ocr_merchant_claims,
)


def _write_ocr_source(root: Path, *, pid: int = 55) -> None:
    root.mkdir(parents=True)
    (root / f"detail_{pid}_ocr.json").write_text(
        json.dumps(
            {
                "pid": pid,
                "name": "测试防晒",
                "images": [
                    {
                        "file": "merchant-claim.jpg",
                        "size": [1440, 2880],
                        "size_kb": 123.4,
                        "ocr_text": (
                            "油皮亲妈 清爽不黏腻 NO.1 "
                            "本品无酒精，敏感肌适用"
                        ),
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _write_review_candidates(path: Path, *, pid: int = 55) -> None:
    rows = [
        {
            "product_id": pid,
            "field_key": "suitable_skin",
            "normalized_value": "油性",
            "display_claim": "油皮亲妈",
            "claim_scope": "ordinary",
            "source_file": f"detail_{pid}_ocr.json",
            "image_file": "merchant-claim.jpg",
            "image_index": 0,
            "rationale": "底妆/护肤语境中的明确适用肤质宣称",
        },
        {
            "product_id": pid,
            "field_key": "texture",
            "normalized_value": "清爽",
            "display_claim": "清爽不黏腻",
            "claim_scope": "ordinary",
            "source_file": f"detail_{pid}_ocr.json",
            "image_file": "merchant-claim.jpg",
            "image_index": 0,
            "rationale": "防晒肤感宣称",
        },
        {
            "product_id": pid,
            "field_key": "suitable_skin",
            "normalized_value": "敏感",
            "display_claim": "敏感肌适用",
            "claim_scope": "ordinary",
            "source_file": f"detail_{pid}_ocr.json",
            "image_file": "merchant-claim.jpg",
            "image_index": 0,
            "rationale": "明确商家适用肤质宣称",
        },
        {
            "product_id": pid,
            "field_key": "safety_claim",
            "normalized_value": "不含酒精",
            "display_claim": "无酒精",
            "claim_scope": "safety_transcript",
            "source_file": f"detail_{pid}_ocr.json",
            "image_file": "merchant-claim.jpg",
            "image_index": 0,
            "rationale": "商家安全宣称仅转述",
        },
    ]
    path.write_text(
        "\n".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True)
            for row in rows
        ),
        encoding="utf-8",
    )


def test_builds_deterministic_dual_form_claim_assets(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "ocr"
    output_root = tmp_path / "output"
    review_path = tmp_path / "review.jsonl"
    _write_ocr_source(source_root)
    _write_review_candidates(review_path)

    first = build_ocr_merchant_claims(
        source_root=source_root,
        review_paths=(review_path,),
        output_root=output_root,
        product_profiles={55: CategoryProfile.SUNCARE},
    )
    first_claims = first.claims_path.read_bytes()
    first_manifest = first.manifest_path.read_bytes()
    second = build_ocr_merchant_claims(
        source_root=source_root,
        review_paths=(review_path,),
        output_root=output_root,
        product_profiles={55: CategoryProfile.SUNCARE},
    )
    assets = load_merchant_claim_assets(
        manifest_path=second.manifest_path,
        claims_path=second.claims_path,
    )

    assert second.claims_path.read_bytes() == first_claims
    assert second.manifest_path.read_bytes() == first_manifest
    assert assets.manifest.source_file_count == 1
    assert assets.manifest.product_count == 1
    ordinary = [
        claim
        for claim in assets.claims
        if claim.claim_scope == "ordinary"
    ]
    safety = [
        claim
        for claim in assets.claims
        if claim.claim_scope == "safety_transcript"
    ]
    assert {
        (
            claim.field_key,
            claim.normalized_value,
            claim.display_claim,
        )
        for claim in ordinary
    } >= {
        ("suitable_skin", "油性", "油皮亲妈"),
        ("texture", "清爽", "清爽不黏腻"),
    }
    assert any(
        claim.display_claim == "无酒精"
        and claim.capabilities == frozenset({"evidence", "display"})
        for claim in safety
    )
    assert all(
        "NO.1" not in claim.display_claim
        for claim in assets.claims
    )
    assert all(
        claim.source_class.value == "merchant_description_ocr"
        and claim.source_locator.startswith(
            "urn:xiaoro:merchant-description-ocr:"
        )
        and "/Users/" not in claim.source_locator
        and claim.display_claim in (
            "油皮亲妈",
            "清爽不黏腻",
            "无酒精",
            "敏感肌适用",
        )
        for claim in assets.claims
    )


def test_concept_audit_normalizes_identity_and_drops_ordinary_safety_duplicate(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "ocr"
    output_root = tmp_path / "output"
    review_path = tmp_path / "review.jsonl"
    audit_path = tmp_path / "concept-audit.jsonl"
    _write_ocr_source(source_root)
    _write_review_candidates(review_path)
    audit_path.write_text(
        "\n".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True)
            for row in (
                {
                    "product_id": 55,
                    "subject_scope": "exact_product",
                    "variant_scope": None,
                    "field_key": "texture",
                    "old_value": "清爽",
                    "decision": "normalize",
                    "new_field_key": "texture",
                    "new_value": "清爽肤感",
                    "rationale": "人工确认同一清爽肤感概念。",
                },
                {
                    "product_id": 55,
                    "subject_scope": "exact_product",
                    "variant_scope": None,
                    "field_key": "suitable_skin",
                    "old_value": "敏感",
                    "decision": "drop_ordinary_duplicate",
                    "new_field_key": None,
                    "new_value": None,
                    "rationale": "安全风格适用宣传由安全证据单独承载。",
                },
            )
        )
        + "\n",
        encoding="utf-8",
    )

    result = build_ocr_merchant_claims(
        source_root=source_root,
        review_paths=(review_path,),
        output_root=output_root,
        product_profiles={55: CategoryProfile.SUNCARE},
        concept_audit_path=audit_path,
    )
    assets = load_merchant_claim_assets(
        manifest_path=result.manifest_path,
        claims_path=result.claims_path,
    )

    assert any(
        claim.field_key == "texture"
        and claim.normalized_value == "清爽肤感"
        and claim.display_claim == "清爽不黏腻"
        for claim in assets.claims
    )
    assert not any(
        claim.field_key == "suitable_skin"
        and claim.normalized_value == "敏感"
        for claim in assets.claims
    )


def test_rejects_ocr_product_outside_canonical_bindings(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "ocr"
    review_path = tmp_path / "review.jsonl"
    _write_ocr_source(source_root, pid=999)
    _write_review_candidates(review_path, pid=999)

    with pytest.raises(
        OcrMerchantClaimBuildError,
        match="unknown canonical product",
    ):
        build_ocr_merchant_claims(
            source_root=source_root,
            review_paths=(review_path,),
            output_root=tmp_path / "output",
            product_profiles={55: CategoryProfile.SUNCARE},
        )


def test_claim_jsonl_is_stable_across_python_hash_seeds(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "ocr"
    review_path = tmp_path / "review.jsonl"
    _write_ocr_source(source_root)
    _write_review_candidates(review_path)
    script = f"""
from pathlib import Path
from app.guide.retrieval.category_profiles import CategoryProfile
from tools.guide_data.build_ocr_merchant_claims import build_ocr_merchant_claims
result = build_ocr_merchant_claims(
    source_root=Path({str(source_root)!r}),
    review_paths=(Path({str(review_path)!r}),),
    output_root=Path(__import__('sys').argv[1]),
    product_profiles={{55: CategoryProfile.SUNCARE}},
)
print(result.claims_path.name)
"""
    names: list[str] = []
    for seed in ("1", "2"):
        environment = dict(os.environ)
        environment["PYTHONHASHSEED"] = seed
        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                script,
                str(tmp_path / f"output-{seed}"),
            ],
            cwd=Path.cwd(),
            env=environment,
            check=True,
            capture_output=True,
            text=True,
        )
        names.append(completed.stdout.strip())

    assert names[0] == names[1]
