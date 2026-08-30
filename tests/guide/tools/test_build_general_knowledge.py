from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from tools.guide_data.build_general_knowledge import (
    KnowledgeBuildError,
    load_general_knowledge_retrieval_profiles,
    parse_knowledge_document,
    parse_knowledge_documents,
    retrieval_terms,
)


_VALID_SOURCE = """# 防晒怎么选

导语。

## 关键成分/原理

SPF针对UVB。

- PA针对UVA。
- 海边需要防水抗汗。
"""


def _write_source(
    tmp_path: Path,
    source: str = _VALID_SOURCE,
    *,
    name: str = "06-防晒怎么选.md",
) -> tuple[Path, Path]:
    repo_root = tmp_path
    source_dir = repo_root / "data" / "knowledge_docs"
    source_dir.mkdir(parents=True, exist_ok=True)
    path = source_dir / name
    path.write_text(source, encoding="utf-8")
    return repo_root, path


def test_parser_preserves_paragraph_list_heading_and_source_order(
    tmp_path: Path,
) -> None:
    repo_root, path = _write_source(tmp_path)

    parsed = parse_knowledge_document(path, repo_root=repo_root)

    assert parsed.document.title == "防晒怎么选"
    assert parsed.document.source_path == (
        "data/knowledge_docs/06-防晒怎么选.md"
    )
    assert parsed.document.source_sha256 == hashlib.sha256(
        _VALID_SOURCE.encode("utf-8")
    ).hexdigest()
    assert [block.section_title for block in parsed.blocks] == [
        "防晒怎么选",
        "关键成分/原理",
        "关键成分/原理",
    ]
    assert [block.section_order for block in parsed.blocks] == [0, 1, 2]
    assert [block.exact_text for block in parsed.blocks] == [
        "导语。",
        "SPF针对UVB。",
        "- PA针对UVA。\n- 海边需要防水抗汗。",
    ]
    assert all(
        block.document_id == parsed.document.document_id
        and block.source_sha256 == parsed.document.source_sha256
        and block.block_sha256
        == hashlib.sha256(
            block.exact_text.encode("utf-8")
        ).hexdigest()
        for block in parsed.blocks
    )


def test_parser_normalizes_line_endings_only(tmp_path: Path) -> None:
    repo_root, path = _write_source(tmp_path)
    path.write_bytes(_VALID_SOURCE.replace("\n", "\r\n").encode("utf-8"))

    parsed = parse_knowledge_document(path, repo_root=repo_root)

    normalized = _VALID_SOURCE
    assert parsed.document.source_sha256 == hashlib.sha256(
        normalized.encode("utf-8")
    ).hexdigest()
    assert parsed.blocks[-1].exact_text == (
        "- PA针对UVA。\n- 海边需要防水抗汗。"
    )


def test_retrieval_terms_come_only_from_source_parts() -> None:
    terms = retrieval_terms(
        "防晒怎么选",
        "关键成分/原理",
        "SPF针对UVB，PA针对UVA。",
    )

    assert terms == tuple(sorted(set(terms)))
    assert {"spf", "uvb", "pa", "uva"} <= set(terms)
    assert {"防", "晒", "防晒", "关键", "成分"} <= set(terms)
    assert "serum" not in terms


@pytest.mark.parametrize(
    ("source", "error"),
    (
        ("没有标题", "exactly one H1"),
        ("# 标题一\n\n# 标题二\n", "exactly one H1"),
        ("标题前内容\n\n# 标题\n", "content before H1"),
        ("# 标题\n\n### 三级\n\n正文\n", "heading order"),
        ("# 标题\n\n## 空章节\n\n## 下一节\n\n正文\n", "empty H2"),
        (
            "# 标题\n\n## 章节\n\n" + "很" * 4001 + "\n",
            "block exceeds",
        ),
    ),
)
def test_parser_rejects_malformed_structure(
    tmp_path: Path,
    source: str,
    error: str,
) -> None:
    repo_root, path = _write_source(tmp_path, source)

    with pytest.raises(KnowledgeBuildError, match=error):
        parse_knowledge_document(path, repo_root=repo_root)


def test_parser_rejects_duplicate_source_path(tmp_path: Path) -> None:
    repo_root, path = _write_source(tmp_path)

    with pytest.raises(KnowledgeBuildError, match="duplicate source path"):
        parse_knowledge_documents(
            (path, path),
            repo_root=repo_root,
        )


def test_parser_rejects_source_outside_repository(tmp_path: Path) -> None:
    repo_root, _ = _write_source(tmp_path)
    outside = tmp_path.parent / "outside-knowledge.md"
    outside.write_text(_VALID_SOURCE, encoding="utf-8")

    with pytest.raises(
        KnowledgeBuildError,
        match="inside repository",
    ):
        parse_knowledge_document(outside, repo_root=repo_root)


def test_retrieval_profile_loader_rejects_duplicate_sources(
    tmp_path: Path,
) -> None:
    row = {
        "source_path": "data/knowledge_docs/06-防晒怎么选.md",
        "primary_concept_ids": ["category", "category.sunscreen"],
        "primary_entity_ids": [],
        "section_relations": {
            "防晒怎么选": ["overview"],
            "关键成分/原理": ["mechanism"],
        },
    }
    profile_path = tmp_path / "profiles.jsonl"
    profile_path.write_text(
        "\n".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True)
            for _ in range(2)
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(KnowledgeBuildError, match="duplicate source"):
        load_general_knowledge_retrieval_profiles(profile_path)
