from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.guide.retrieval.general_knowledge_assets import (
    GeneralKnowledgeAssetIntegrityError,
    load_general_knowledge_assets,
)
from tools.guide_data.audit_general_knowledge import (
    materialize_general_knowledge_reviews,
)
from tools.guide_data.build_general_knowledge import (
    build_general_knowledge_assets,
    parse_knowledge_documents,
)


_SOURCE = """# 防晒怎么选

## 原理

SPF针对UVB，PA针对UVA。

## 收束

防晒要按场景选择。
"""


def _write_candidates(
    source_dir: Path,
    candidate_path: Path,
    *,
    repo_root: Path,
) -> None:
    parsed = parse_knowledge_documents(
        tuple(source_dir.glob("*.md")),
        repo_root=repo_root,
    )
    candidate_path.write_text(
        "".join(
            json.dumps(
                block.model_dump(mode="json"),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
            for document in parsed
            for block in document.blocks
        ),
        encoding="utf-8",
    )


def _built_fixture(tmp_path: Path):
    source_dir = tmp_path / "data" / "knowledge_docs"
    source_dir.mkdir(parents=True)
    (source_dir / "06-防晒怎么选.md").write_text(
        _SOURCE,
        encoding="utf-8",
    )
    candidate_path = tmp_path / "candidates.jsonl"
    _write_candidates(
        source_dir,
        candidate_path,
        repo_root=tmp_path,
    )
    decisions = tmp_path / "decisions.jsonl"
    decisions.write_text(
        json.dumps(
            {
                "source_path": (
                    "data/knowledge_docs/06-防晒怎么选.md"
                ),
                "dispositions": [
                    "general_answer",
                    "reject_filler",
                ],
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )
    review_dir = tmp_path / "data" / "guide_general_knowledge" / "reviews"
    materialize_general_knowledge_reviews(
        candidate_path=candidate_path,
        decision_catalog_path=decisions,
        review_dir=review_dir,
    )
    output_dir = tmp_path / "data" / "guide_general_knowledge"
    built = build_general_knowledge_assets(
        source_dir=source_dir,
        review_dir=review_dir,
        output_dir=output_dir,
        repo_root=tmp_path,
        asset_version="2026-08-15",
    )
    return built, source_dir, review_dir, output_dir


def test_asset_is_content_addressed_and_excludes_rejected_blocks(
    tmp_path: Path,
) -> None:
    built, _, _, _ = _built_fixture(tmp_path)

    assets = load_general_knowledge_assets(
        built.manifest_path,
        expected_manifest_sha256=built.manifest_sha256,
        repo_root=tmp_path,
    )

    assert built.blocks_path.name == (
        f"general_knowledge_v1.{built.blocks_sha256}.jsonl"
    )
    assert assets.manifest.manifest_sha256 == built.manifest_sha256
    assert assets.manifest.candidate_count == 2
    assert assets.manifest.block_count == 1
    assert assets.manifest.decision_counts == {
        "escalation_only": 0,
        "general_answer": 1,
        "product_specific_redirect": 0,
        "rejected": 1,
    }
    assert len(assets.blocks) == 1
    assert all(
        block.review_decision != "rejected"
        for block in assets.blocks
    )


def test_asset_build_is_byte_identical(tmp_path: Path) -> None:
    built, source_dir, review_dir, _ = _built_fixture(tmp_path)
    second_output = tmp_path / "second" / "data" / "guide_general_knowledge"

    second = build_general_knowledge_assets(
        source_dir=source_dir,
        review_dir=review_dir,
        output_dir=second_output,
        repo_root=tmp_path,
        asset_version="2026-08-15",
    )

    assert second.blocks_path.read_bytes() == built.blocks_path.read_bytes()
    assert second.manifest_path.read_bytes() == (
        built.manifest_path.read_bytes()
    )
    assert second.manifest_sha256 == built.manifest_sha256


def test_runtime_rejects_manifest_lock_mismatch(
    tmp_path: Path,
) -> None:
    built, _, _, _ = _built_fixture(tmp_path)

    with pytest.raises(
        GeneralKnowledgeAssetIntegrityError,
        match="manifest lock mismatch",
    ):
        load_general_knowledge_assets(
            built.manifest_path,
            expected_manifest_sha256="f" * 64,
            repo_root=tmp_path,
        )


def test_runtime_rejects_block_asset_tampering(
    tmp_path: Path,
) -> None:
    built, _, _, _ = _built_fixture(tmp_path)
    built.blocks_path.write_bytes(
        built.blocks_path.read_bytes() + b" "
    )

    with pytest.raises(
        GeneralKnowledgeAssetIntegrityError,
        match="block JSONL SHA mismatch",
    ):
        load_general_knowledge_assets(
            built.manifest_path,
            expected_manifest_sha256=built.manifest_sha256,
            repo_root=tmp_path,
        )


def test_runtime_rejects_source_document_drift(
    tmp_path: Path,
) -> None:
    built, source_dir, _, _ = _built_fixture(tmp_path)
    (source_dir / "06-防晒怎么选.md").write_text(
        _SOURCE + "\n新内容。\n",
        encoding="utf-8",
    )

    with pytest.raises(
        GeneralKnowledgeAssetIntegrityError,
        match="source SHA mismatch",
    ):
        load_general_knowledge_assets(
            built.manifest_path,
            expected_manifest_sha256=built.manifest_sha256,
            repo_root=tmp_path,
        )


def test_runtime_rejects_review_drift(tmp_path: Path) -> None:
    built, _, review_dir, _ = _built_fixture(tmp_path)
    review_path = next(review_dir.glob("*.jsonl"))
    review_path.write_bytes(review_path.read_bytes() + b" ")

    with pytest.raises(
        GeneralKnowledgeAssetIntegrityError,
        match="review SHA inventory mismatch",
    ):
        load_general_knowledge_assets(
            built.manifest_path,
            expected_manifest_sha256=built.manifest_sha256,
            repo_root=tmp_path,
        )
