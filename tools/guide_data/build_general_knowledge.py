from __future__ import annotations

import argparse
from collections.abc import Sequence
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import tempfile

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from app.guide.retrieval.general_knowledge_contracts import (
    GeneralKnowledgeBlock,
    GeneralKnowledgeDocument,
    GeneralKnowledgeManifest,
    GeneralKnowledgeRetrievalProfile,
    general_knowledge_id,
)
from app.guide.retrieval.general_knowledge_ontology import (
    match_knowledge_concepts,
    match_knowledge_entities,
)
from app.guide.retrieval.general_knowledge_terms import (
    general_knowledge_terms as retrieval_terms,
)


_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d+\.)\s+")
_MAX_BLOCK_CHARS = 4000


class KnowledgeBuildError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class GeneralKnowledgeBuildResult:
    manifest_path: Path
    blocks_path: Path
    manifest_sha256: str
    blocks_sha256: str
    candidate_count: int
    block_count: int


class _StrictFrozenModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
        protected_namespaces=(),
    )


class KnowledgeCandidateBlock(_StrictFrozenModel):
    candidate_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    document_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    title: str = Field(min_length=1, max_length=256)
    section_title: str = Field(min_length=1, max_length=256)
    exact_text: str = Field(min_length=1, max_length=_MAX_BLOCK_CHARS)
    source_path: str = Field(min_length=1, max_length=512)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    block_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    section_order: int = Field(ge=0)
    retrieval_terms: tuple[str, ...] = Field(
        min_length=1,
        max_length=2048,
    )

    @field_validator("retrieval_terms", mode="before")
    @classmethod
    def freeze_terms(cls, value: object) -> object:
        if isinstance(value, list):
            return tuple(value)
        return value

    @model_validator(mode="after")
    def validate_candidate(self) -> KnowledgeCandidateBlock:
        if self.block_sha256 != hashlib.sha256(
            self.exact_text.encode("utf-8")
        ).hexdigest():
            raise ValueError("candidate block SHA mismatch")
        if (
            self.retrieval_terms
            != tuple(sorted(set(self.retrieval_terms)))
        ):
            raise ValueError(
                "candidate retrieval terms must be sorted and unique"
            )
        expected = general_knowledge_id(candidate_identity(self))
        if self.candidate_id != expected:
            raise ValueError("candidate ID mismatch")
        return self


class ParsedKnowledgeDocument(_StrictFrozenModel):
    document: GeneralKnowledgeDocument
    blocks: tuple[KnowledgeCandidateBlock, ...] = Field(min_length=1)

    @field_validator("blocks", mode="before")
    @classmethod
    def freeze_blocks(cls, value: object) -> object:
        if isinstance(value, list):
            return tuple(value)
        return value

    @model_validator(mode="after")
    def validate_blocks(self) -> ParsedKnowledgeDocument:
        if any(
            block.document_id != self.document.document_id
            or block.source_path != self.document.source_path
            or block.source_sha256 != self.document.source_sha256
            for block in self.blocks
        ):
            raise ValueError("candidate block source identity mismatch")
        if tuple(block.section_order for block in self.blocks) != tuple(
            range(len(self.blocks))
        ):
            raise ValueError("candidate block order must be contiguous")
        return self


def load_general_knowledge_retrieval_profiles(
    path: Path,
) -> tuple[GeneralKnowledgeRetrievalProfile, ...]:
    profile_path = Path(path)
    try:
        lines = profile_path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise KnowledgeBuildError(
            "general knowledge retrieval profile is unavailable"
        ) from exc
    if not lines or any(not line for line in lines):
        raise KnowledgeBuildError(
            "general knowledge retrieval profile is empty or malformed"
        )
    profiles: list[GeneralKnowledgeRetrievalProfile] = []
    for line_number, line in enumerate(lines, start=1):
        try:
            profile = GeneralKnowledgeRetrievalProfile.model_validate_json(
                line,
                strict=True,
            )
        except ValueError as exc:
            raise KnowledgeBuildError(
                "invalid general knowledge retrieval profile line "
                f"{line_number}"
            ) from exc
        profiles.append(profile)
    source_paths = [profile.source_path for profile in profiles]
    if len(source_paths) != len(set(source_paths)):
        raise KnowledgeBuildError(
            "general knowledge retrieval profile has duplicate source"
        )
    return tuple(profiles)


def candidate_identity(
    block: KnowledgeCandidateBlock,
) -> dict[str, object]:
    return {
        "document_id": block.document_id,
        "title": block.title,
        "section_title": block.section_title,
        "exact_text": block.exact_text,
        "source_path": block.source_path,
        "source_sha256": block.source_sha256,
        "block_sha256": block.block_sha256,
        "section_order": block.section_order,
    }


def parse_knowledge_document(
    path: Path,
    *,
    repo_root: Path,
) -> ParsedKnowledgeDocument:
    source_file = Path(path)
    root = Path(repo_root).resolve()
    try:
        resolved = source_file.resolve(strict=True)
        relative = resolved.relative_to(root)
    except (OSError, ValueError) as exc:
        raise KnowledgeBuildError(
            "knowledge source must be inside repository"
        ) from exc
    source_path = relative.as_posix()
    try:
        raw = resolved.read_bytes()
        source = raw.decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise KnowledgeBuildError(
            "knowledge source must be readable UTF-8"
        ) from exc
    normalized = source.replace("\r\n", "\n").replace("\r", "\n")
    lines = normalized.splitlines()

    headings = [
        (index, match)
        for index, line in enumerate(lines)
        if (match := _HEADING.fullmatch(line)) is not None
    ]
    h1_headings = [
        (index, match)
        for index, match in headings
        if len(match.group(1)) == 1
    ]
    if len(h1_headings) != 1:
        raise KnowledgeBuildError(
            "knowledge document must have exactly one H1"
        )
    h1_index, h1_match = h1_headings[0]
    if any(line.strip() for line in lines[:h1_index]):
        raise KnowledgeBuildError(
            "knowledge document has content before H1"
        )
    if any(
        len(match.group(1)) > 2
        for _, match in headings
    ):
        raise KnowledgeBuildError(
            "knowledge document heading order is invalid"
        )
    title = h1_match.group(2).strip()
    if not title:
        raise KnowledgeBuildError("knowledge document H1 is empty")

    source_sha256 = hashlib.sha256(
        normalized.encode("utf-8")
    ).hexdigest()
    document_payload: dict[str, object] = {
        "title": title,
        "source_path": source_path,
        "source_sha256": source_sha256,
        "document_kind": "educational_seed",
    }
    try:
        document = GeneralKnowledgeDocument.model_validate(
            {
                "document_id": general_knowledge_id(document_payload),
                **document_payload,
            },
            strict=True,
        )
    except ValueError as exc:
        raise KnowledgeBuildError(
            "knowledge document source contract is invalid"
        ) from exc

    blocks: list[KnowledgeCandidateBlock] = []
    current_section = title
    current_h2: str | None = None
    current_h2_has_block = False
    buffer: list[str] = []
    buffer_kind: str | None = None

    def flush_buffer() -> None:
        nonlocal buffer, buffer_kind, current_h2_has_block
        if not buffer:
            return
        exact_text = "\n".join(buffer).strip()
        buffer = []
        buffer_kind = None
        if not exact_text:
            return
        if len(exact_text) > _MAX_BLOCK_CHARS:
            raise KnowledgeBuildError(
                "knowledge block exceeds maximum length"
            )
        block_sha256 = hashlib.sha256(
            exact_text.encode("utf-8")
        ).hexdigest()
        identity: dict[str, object] = {
            "document_id": document.document_id,
            "title": title,
            "section_title": current_section,
            "exact_text": exact_text,
            "source_path": source_path,
            "source_sha256": source_sha256,
            "block_sha256": block_sha256,
            "section_order": len(blocks),
        }
        blocks.append(
            KnowledgeCandidateBlock.model_validate(
                {
                    "candidate_id": general_knowledge_id(identity),
                    **identity,
                    "retrieval_terms": retrieval_terms(
                        title,
                        current_section,
                        exact_text,
                    ),
                },
                strict=True,
            )
        )
        if current_h2 is not None:
            current_h2_has_block = True

    for index, line in enumerate(lines[h1_index + 1:], start=h1_index + 1):
        heading = _HEADING.fullmatch(line)
        if heading is not None:
            flush_buffer()
            level = len(heading.group(1))
            if level == 1:
                raise KnowledgeBuildError(
                    "knowledge document must have exactly one H1"
                )
            if level != 2:
                raise KnowledgeBuildError(
                    "knowledge document heading order is invalid"
                )
            if current_h2 is not None and not current_h2_has_block:
                raise KnowledgeBuildError(
                    f"knowledge document has empty H2: {current_h2}"
                )
            current_h2 = heading.group(2).strip()
            if not current_h2:
                raise KnowledgeBuildError(
                    "knowledge document H2 is empty"
                )
            current_section = current_h2
            current_h2_has_block = False
            continue
        if not line.strip():
            flush_buffer()
            continue
        kind = "list" if _LIST_ITEM.match(line) is not None else "paragraph"
        if buffer and kind != buffer_kind:
            flush_buffer()
        buffer_kind = kind
        buffer.append(line)

    flush_buffer()
    if current_h2 is not None and not current_h2_has_block:
        raise KnowledgeBuildError(
            f"knowledge document has empty H2: {current_h2}"
        )
    if not blocks:
        raise KnowledgeBuildError(
            "knowledge document has no answerable blocks"
        )
    return ParsedKnowledgeDocument(
        document=document,
        blocks=tuple(blocks),
    )


def parse_knowledge_documents(
    paths: Sequence[Path],
    *,
    repo_root: Path,
) -> tuple[ParsedKnowledgeDocument, ...]:
    if isinstance(paths, (str, bytes)) or not isinstance(paths, Sequence):
        raise TypeError("knowledge source paths must be a sequence")
    resolved_paths = [Path(path).resolve() for path in paths]
    if len(resolved_paths) != len(set(resolved_paths)):
        raise KnowledgeBuildError("duplicate source path")
    parsed = tuple(
        parse_knowledge_document(path, repo_root=repo_root)
        for path in sorted(
            resolved_paths,
            key=lambda item: item.as_posix(),
        )
    )
    source_hashes = [
        item.document.source_sha256
        for item in parsed
    ]
    if len(source_hashes) != len(set(source_hashes)):
        raise KnowledgeBuildError("duplicate source hash")
    return parsed


def _write_candidates(
    parsed: Sequence[ParsedKnowledgeDocument],
    *,
    output_path: Path,
) -> tuple[int, str]:
    blocks = [
        block
        for document in parsed
        for block in document.blocks
    ]
    data = (
        "\n".join(
            json.dumps(
                block.model_dump(mode="json"),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            for block in blocks
        )
        + "\n"
    ).encode("utf-8")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(data)
    return len(blocks), hashlib.sha256(data).hexdigest()


def _serialize_block(block: object) -> dict[str, object]:
    if not hasattr(block, "model_dump"):
        raise TypeError("knowledge block must support model_dump")
    payload = block.model_dump(mode="json")
    payload["allowed_uses"] = sorted(block.allowed_uses)
    payload["forbidden_uses"] = sorted(block.forbidden_uses)
    return payload


def build_general_knowledge_assets(
    *,
    source_dir: Path,
    review_dir: Path,
    retrieval_profile_path: Path,
    output_dir: Path,
    repo_root: Path,
    asset_version: str,
) -> GeneralKnowledgeBuildResult:
    if (
        not isinstance(asset_version, str)
        or not asset_version.strip()
        or len(asset_version) > 64
    ):
        raise ValueError("asset version must be nonempty")
    parsed = parse_knowledge_documents(
        tuple(Path(source_dir).glob("*.md")),
        repo_root=Path(repo_root),
    )
    profiles = load_general_knowledge_retrieval_profiles(
        retrieval_profile_path
    )
    profiles_by_source = {
        profile.source_path: profile for profile in profiles
    }
    source_paths = {
        document.document.source_path for document in parsed
    }
    if set(profiles_by_source) != source_paths:
        raise KnowledgeBuildError(
            "general knowledge retrieval profile source inventory mismatch"
        )
    for document in parsed:
        profile = profiles_by_source[document.document.source_path]
        section_titles = {
            block.section_title for block in document.blocks
        }
        if set(profile.section_relations) != section_titles:
            raise KnowledgeBuildError(
                "general knowledge retrieval profile section inventory "
                f"mismatch: {document.document.source_path}"
            )
    review_paths = tuple(sorted(Path(review_dir).glob("*.jsonl")))
    if not review_paths:
        raise KnowledgeBuildError(
            "general knowledge reviews are unavailable"
        )

    from tools.guide_data.audit_general_knowledge import (
        audit_general_knowledge,
    )

    with tempfile.TemporaryDirectory(
        prefix="xiaoro-general-knowledge-",
    ) as temporary:
        candidate_path = Path(temporary) / "candidates.jsonl"
        _write_candidates(parsed, output_path=candidate_path)
        audit = audit_general_knowledge(
            candidate_path=candidate_path,
            review_paths=review_paths,
        )
    if not audit.report.clean:
        raise KnowledgeBuildError(
            "general knowledge audit must be clean before publication"
        )
    enriched_blocks = tuple(
        GeneralKnowledgeBlock.model_validate(
            {
                **block.model_dump(mode="python"),
                "primary_concept_ids": profile.primary_concept_ids,
                "mentioned_concept_ids": tuple(sorted({
                    match.identifier
                    for match in match_knowledge_concepts(
                        block.exact_text
                    )
                })),
                "primary_entity_ids": profile.primary_entity_ids,
                "mentioned_entity_ids": tuple(sorted({
                    match.identifier
                    for match in match_knowledge_entities(
                        block.exact_text
                    )
                })),
                "relation_intents": profile.section_relations[
                    block.section_title
                ],
            },
            strict=True,
        )
        for block in audit.blocks
        for profile in (profiles_by_source[block.source_path],)
    )
    published_blocks = tuple(
        sorted(
            (
                block
                for block in enriched_blocks
                if block.review_decision != "rejected"
            ),
            key=lambda block: (
                block.source_path,
                block.section_order,
                block.knowledge_id,
            ),
        )
    )
    blocks_bytes = (
        "\n".join(
            json.dumps(
                _serialize_block(block),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            for block in published_blocks
        )
        + "\n"
    ).encode("utf-8")
    blocks_sha256 = hashlib.sha256(blocks_bytes).hexdigest()
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    blocks_path = (
        destination
        / f"general_knowledge_v2.{blocks_sha256}.jsonl"
    )
    blocks_path.write_bytes(blocks_bytes)

    decision_counts = {
        "general_answer": audit.report.general_answer,
        "escalation_only": audit.report.escalation_only,
        "product_specific_redirect": (
            audit.report.product_specific_redirect
        ),
        "rejected": audit.report.rejected,
    }
    allowed_use_counts = {
        use: sum(
            use in block.allowed_uses
            for block in published_blocks
        )
        for use in (
            "answer",
            "citation",
            "followup",
            "medical_escalation",
        )
    }
    manifest_payload: dict[str, object] = {
        "schema_version": "guide-general-knowledge-v2",
        "asset_id": "guide-general-knowledge-v2",
        "asset_version": asset_version,
        "blocks_file": blocks_path.name,
        "blocks_sha256": blocks_sha256,
        "block_count": len(published_blocks),
        "candidate_count": audit.report.candidate_total,
        "document_count": len(parsed),
        "source_document_ids": sorted(
            item.document.document_id
            for item in parsed
        ),
        "source_sha256s": sorted(
            item.document.source_sha256
            for item in parsed
        ),
        "review_file_sha256s": sorted(
            hashlib.sha256(path.read_bytes()).hexdigest()
            for path in review_paths
        ),
        "retrieval_profile_path": (
            Path(retrieval_profile_path)
            .resolve()
            .relative_to(Path(repo_root).resolve())
            .as_posix()
        ),
        "retrieval_profile_sha256": hashlib.sha256(
            Path(retrieval_profile_path).read_bytes()
        ).hexdigest(),
        "decision_counts": decision_counts,
        "allowed_use_counts": allowed_use_counts,
    }
    manifest_sha256 = general_knowledge_id(manifest_payload)
    manifest = GeneralKnowledgeManifest.model_validate(
        {
            **manifest_payload,
            "manifest_sha256": manifest_sha256,
        },
        strict=True,
    )
    manifest_path = (
        destination / "general_knowledge_v2_manifest.json"
    )
    manifest_path.write_text(
        json.dumps(
            manifest.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )
    return GeneralKnowledgeBuildResult(
        manifest_path=manifest_path,
        blocks_path=blocks_path,
        manifest_sha256=manifest_sha256,
        blocks_sha256=blocks_sha256,
        candidate_count=audit.report.candidate_total,
        block_count=len(published_blocks),
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build Guide general-knowledge review candidates.",
    )
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--candidate-output", type=Path)
    parser.add_argument("--review-dir", type=Path)
    parser.add_argument("--retrieval-profile", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--asset-version", default="2026-08-15")
    args = parser.parse_args(argv)
    repo_root = Path.cwd().resolve()
    production_mode = (
        args.review_dir is not None
        or args.retrieval_profile is not None
        or args.output_dir is not None
    )
    if production_mode:
        if (
            args.candidate_output is not None
            or args.review_dir is None
            or args.retrieval_profile is None
            or args.output_dir is None
        ):
            parser.error(
                "production mode requires review-dir and output-dir only"
            )
        built = build_general_knowledge_assets(
            source_dir=args.source_dir,
            review_dir=args.review_dir,
            retrieval_profile_path=args.retrieval_profile,
            output_dir=args.output_dir,
            repo_root=repo_root,
            asset_version=args.asset_version,
        )
        print(
            json.dumps(
                {
                    "block_count": built.block_count,
                    "blocks_sha256": built.blocks_sha256,
                    "candidate_count": built.candidate_count,
                    "manifest_sha256": built.manifest_sha256,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return 0
    if args.candidate_output is None:
        parser.error("candidate mode requires candidate-output")
    parsed = parse_knowledge_documents(
        tuple(args.source_dir.glob("*.md")),
        repo_root=repo_root,
    )
    candidate_count, candidate_sha256 = _write_candidates(
        parsed,
        output_path=args.candidate_output,
    )
    print(
        json.dumps(
            {
                "candidate_count": candidate_count,
                "candidate_sha256": candidate_sha256,
                "document_count": len(parsed),
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "GeneralKnowledgeBuildResult",
    "KnowledgeBuildError",
    "KnowledgeCandidateBlock",
    "ParsedKnowledgeDocument",
    "build_general_knowledge_assets",
    "candidate_identity",
    "load_general_knowledge_retrieval_profiles",
    "main",
    "parse_knowledge_document",
    "parse_knowledge_documents",
    "retrieval_terms",
]
