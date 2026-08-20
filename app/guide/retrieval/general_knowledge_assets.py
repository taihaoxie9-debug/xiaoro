from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pydantic import (
    BaseModel,
    ConfigDict,
    field_validator,
)

from app.guide.retrieval.general_knowledge_contracts import (
    GeneralKnowledgeBlock,
    GeneralKnowledgeDocument,
    GeneralKnowledgeManifest,
    general_knowledge_id,
)


class GeneralKnowledgeAssetIntegrityError(RuntimeError):
    pass


class GeneralKnowledgeAssets(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
        protected_namespaces=(),
    )

    manifest: GeneralKnowledgeManifest
    blocks: tuple[GeneralKnowledgeBlock, ...]

    @field_validator("blocks", mode="before")
    @classmethod
    def freeze_blocks(cls, value: object) -> object:
        if isinstance(value, list):
            return tuple(value)
        return value


def _read_manifest(path: Path) -> tuple[dict[str, object], bytes]:
    try:
        raw = path.read_bytes()
        payload = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GeneralKnowledgeAssetIntegrityError(
            "general knowledge manifest is invalid"
        ) from exc
    if not isinstance(payload, dict):
        raise GeneralKnowledgeAssetIntegrityError(
            "general knowledge manifest must be an object"
        )
    return payload, raw


def _source_sha256(path: Path) -> str:
    try:
        source = path.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise GeneralKnowledgeAssetIntegrityError(
            "general knowledge source is unavailable"
        ) from exc
    normalized = source.replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def load_general_knowledge_assets(
    manifest_path: Path,
    *,
    expected_manifest_sha256: str,
    repo_root: Path | None = None,
) -> GeneralKnowledgeAssets:
    manifest_file = Path(manifest_path)
    payload, _ = _read_manifest(manifest_file)
    unsigned = {
        key: value
        for key, value in payload.items()
        if key != "manifest_sha256"
    }
    actual_manifest_sha256 = general_knowledge_id(unsigned)
    if payload.get("manifest_sha256") != actual_manifest_sha256:
        raise GeneralKnowledgeAssetIntegrityError(
            "general knowledge manifest SHA mismatch"
        )
    if (
        not isinstance(expected_manifest_sha256, str)
        or len(expected_manifest_sha256) != 64
        or actual_manifest_sha256 != expected_manifest_sha256
    ):
        raise GeneralKnowledgeAssetIntegrityError(
            "general knowledge manifest lock mismatch"
        )
    try:
        manifest = GeneralKnowledgeManifest.model_validate(
            payload,
            strict=True,
        )
    except ValueError as exc:
        raise GeneralKnowledgeAssetIntegrityError(
            "general knowledge manifest contract is invalid"
        ) from exc
    if manifest_file.name != "general_knowledge_v1_manifest.json":
        raise GeneralKnowledgeAssetIntegrityError(
            "general knowledge manifest filename is invalid"
        )

    blocks_path = manifest_file.parent / manifest.blocks_file
    try:
        blocks_bytes = blocks_path.read_bytes()
    except OSError as exc:
        raise GeneralKnowledgeAssetIntegrityError(
            "general knowledge block JSONL is unavailable"
        ) from exc
    if hashlib.sha256(blocks_bytes).hexdigest() != manifest.blocks_sha256:
        raise GeneralKnowledgeAssetIntegrityError(
            "general knowledge block JSONL SHA mismatch"
        )
    expected_blocks_name = (
        f"general_knowledge_v1.{manifest.blocks_sha256}.jsonl"
    )
    if blocks_path.name != expected_blocks_name:
        raise GeneralKnowledgeAssetIntegrityError(
            "general knowledge block JSONL is not content addressed"
        )
    try:
        lines = blocks_bytes.decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise GeneralKnowledgeAssetIntegrityError(
            "general knowledge block JSONL is not UTF-8"
        ) from exc
    if len(lines) != manifest.block_count or any(not line for line in lines):
        raise GeneralKnowledgeAssetIntegrityError(
            "general knowledge block count mismatch"
        )
    blocks: list[GeneralKnowledgeBlock] = []
    for line_number, line in enumerate(lines, start=1):
        try:
            block = GeneralKnowledgeBlock.model_validate_json(
                line,
                strict=True,
            )
        except ValueError as exc:
            raise GeneralKnowledgeAssetIntegrityError(
                f"invalid general knowledge block line {line_number}"
            ) from exc
        if block.review_decision == "rejected":
            raise GeneralKnowledgeAssetIntegrityError(
                "rejected general knowledge block was published"
            )
        blocks.append(block)
    expected_order = sorted(
        blocks,
        key=lambda block: (
            block.source_path,
            block.section_order,
            block.knowledge_id,
        ),
    )
    ids = [block.knowledge_id for block in blocks]
    if blocks != expected_order or len(ids) != len(set(ids)):
        raise GeneralKnowledgeAssetIntegrityError(
            "general knowledge block order or identity is invalid"
        )

    root = (
        Path(repo_root).resolve()
        if repo_root is not None
        else manifest_file.resolve().parents[2]
    )
    source_identity: dict[
        str,
        tuple[str, str, str],
    ] = {}
    for block in blocks:
        identity = (
            block.document_id,
            block.title,
            block.source_sha256,
        )
        previous = source_identity.setdefault(
            block.source_path,
            identity,
        )
        if previous != identity:
            raise GeneralKnowledgeAssetIntegrityError(
                "general knowledge source identity is inconsistent"
            )
    documents: list[GeneralKnowledgeDocument] = []
    for source_path, (
        document_id,
        title,
        source_sha256,
    ) in source_identity.items():
        current_sha256 = _source_sha256(root / source_path)
        if current_sha256 != source_sha256:
            raise GeneralKnowledgeAssetIntegrityError(
                "general knowledge source SHA mismatch"
            )
        try:
            document = GeneralKnowledgeDocument(
                document_id=document_id,
                title=title,
                source_path=source_path,
                source_sha256=source_sha256,
                document_kind="educational_seed",
            )
        except ValueError as exc:
            raise GeneralKnowledgeAssetIntegrityError(
                "general knowledge document identity is invalid"
            ) from exc
        documents.append(document)
    if (
        tuple(sorted(item.document_id for item in documents))
        != manifest.source_document_ids
        or tuple(sorted(item.source_sha256 for item in documents))
        != manifest.source_sha256s
        or len(documents) != manifest.document_count
    ):
        raise GeneralKnowledgeAssetIntegrityError(
            "general knowledge source inventory mismatch"
        )

    review_hashes = tuple(
        sorted(
            hashlib.sha256(path.read_bytes()).hexdigest()
            for path in (
                manifest_file.parent / "reviews"
            ).glob("*.jsonl")
        )
    )
    if review_hashes != manifest.review_file_sha256s:
        raise GeneralKnowledgeAssetIntegrityError(
            "general knowledge review SHA inventory mismatch"
        )
    published_decisions = {
        decision: sum(
            block.review_decision == decision
            for block in blocks
        )
        for decision in (
            "general_answer",
            "escalation_only",
            "product_specific_redirect",
        )
    }
    if any(
        published_decisions[decision]
        != manifest.decision_counts.get(decision, 0)
        for decision in published_decisions
    ):
        raise GeneralKnowledgeAssetIntegrityError(
            "general knowledge decision count mismatch"
        )
    allowed_use_counts = {
        use: sum(
            use in block.allowed_uses
            for block in blocks
        )
        for use in (
            "answer",
            "citation",
            "followup",
            "medical_escalation",
        )
    }
    if allowed_use_counts != manifest.allowed_use_counts:
        raise GeneralKnowledgeAssetIntegrityError(
            "general knowledge permission count mismatch"
        )
    try:
        return GeneralKnowledgeAssets(
            manifest=manifest,
            blocks=tuple(blocks),
        )
    except ValueError as exc:
        raise GeneralKnowledgeAssetIntegrityError(
            "general knowledge asset contract is invalid"
        ) from exc


__all__ = [
    "GeneralKnowledgeAssetIntegrityError",
    "GeneralKnowledgeAssets",
    "load_general_knowledge_assets",
]
