from __future__ import annotations

import argparse
from collections.abc import Sequence
import json
from pathlib import Path
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
)

from app.guide.retrieval.general_knowledge_contracts import (
    GeneralKnowledgeBlock,
    KnowledgeForbiddenUse,
    KnowledgeReviewDecision,
    KnowledgeUse,
)
from tools.guide_data.build_general_knowledge import (
    KnowledgeCandidateBlock,
)


ReviewContentScope = Literal[
    "general",
    "medical_boundary",
    "product_specific",
    "unsupported",
]
ManualDisposition = Literal[
    "general_answer",
    "medical_escalation",
    "product_redirect",
    "reject_unsupported",
    "reject_filler",
]

_MANDATORY_FORBIDDEN_USES = (
    "hard_filter",
    "product_fact",
    "profile_write",
    "safety_guarantee",
    "soft_rank",
)
_DISPOSITION_POLICY: dict[
    ManualDisposition,
    dict[str, object],
] = {
    "general_answer": {
        "content_scope": "general",
        "review_decision": "general_answer",
        "allowed_uses": ["answer", "citation", "followup"],
        "review_rationale": (
            "逐块核验为通用教育内容，不指向具体商品，"
            "不提供诊断或安全保证。"
        ),
    },
    "medical_escalation": {
        "content_scope": "medical_boundary",
        "review_decision": "escalation_only",
        "allowed_uses": [
            "citation",
            "followup",
            "medical_escalation",
        ],
        "review_rationale": (
            "包含孕期、用药、开放伤口或持续严重症状边界，"
            "仅用于专业就医升级提醒。"
        ),
    },
    "product_redirect": {
        "content_scope": "product_specific",
        "review_decision": "product_specific_redirect",
        "allowed_uses": ["citation", "followup"],
        "review_rationale": (
            "包含具体商品配方、版本、价格或横向结论，"
            "只能重定向到当前 ProductEvidence。"
        ),
    },
    "reject_unsupported": {
        "content_scope": "unsupported",
        "review_decision": "rejected",
        "allowed_uses": [],
        "review_rationale": (
            "包含无充分来源的绝对化、过度概括或相互矛盾内容，"
            "不发布为运行时知识。"
        ),
    },
    "reject_filler": {
        "content_scope": "unsupported",
        "review_decision": "rejected",
        "allowed_uses": [],
        "review_rationale": (
            "仅为修辞性收束或重复填充，没有独立回答价值，"
            "不发布为运行时知识。"
        ),
    },
}


class KnowledgeAuditError(ValueError):
    pass


class _StrictFrozenModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
        protected_namespaces=(),
    )


class GeneralKnowledgeReview(_StrictFrozenModel):
    candidate_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    block_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    content_scope: ReviewContentScope
    review_decision: KnowledgeReviewDecision
    allowed_uses: frozenset[KnowledgeUse]
    forbidden_uses: frozenset[KnowledgeForbiddenUse]
    review_rationale: str = Field(min_length=1, max_length=1000)

    @field_validator(
        "allowed_uses",
        "forbidden_uses",
        mode="before",
    )
    @classmethod
    def freeze_uses(cls, value: object) -> object:
        if isinstance(value, (list, tuple, set)):
            return frozenset(value)
        return value

    @field_validator("review_rationale")
    @classmethod
    def validate_rationale(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("review rationale must be trimmed")
        return value


class GeneralKnowledgeDecisionCatalogRow(_StrictFrozenModel):
    source_path: str = Field(min_length=1, max_length=512)
    dispositions: tuple[ManualDisposition, ...] = Field(max_length=256)

    @field_validator("dispositions", mode="before")
    @classmethod
    def freeze_dispositions(cls, value: object) -> object:
        if isinstance(value, list):
            return tuple(value)
        return value


class GeneralKnowledgeAuditReport(_StrictFrozenModel):
    candidate_total: int = Field(ge=0)
    reviewed_total: int = Field(ge=0)
    missing_total: int = Field(ge=0)
    general_answer: int = Field(ge=0)
    escalation_only: int = Field(ge=0)
    product_specific_redirect: int = Field(ge=0)
    rejected: int = Field(ge=0)
    permission_mismatches: int = Field(ge=0)
    invalid_reviews: int = Field(ge=0)
    duplicate_reviews: int = Field(ge=0)
    unknown_reviews: int = Field(ge=0)
    source_mismatches: int = Field(ge=0)
    clean: bool


class GeneralKnowledgeAudit(_StrictFrozenModel):
    report: GeneralKnowledgeAuditReport
    blocks: tuple[GeneralKnowledgeBlock, ...]

    @field_validator("blocks", mode="before")
    @classmethod
    def freeze_blocks(cls, value: object) -> object:
        if isinstance(value, list):
            return tuple(value)
        return value


def _load_candidates(path: Path) -> tuple[KnowledgeCandidateBlock, ...]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise KnowledgeAuditError(
            "knowledge candidate file is unavailable"
        ) from exc
    if not lines or any(not line for line in lines):
        raise KnowledgeAuditError(
            "knowledge candidate JSONL is empty or contains blank lines"
        )
    candidates: list[KnowledgeCandidateBlock] = []
    for line_number, line in enumerate(lines, start=1):
        try:
            candidate = KnowledgeCandidateBlock.model_validate_json(
                line,
                strict=True,
            )
        except ValueError as exc:
            raise KnowledgeAuditError(
                f"invalid knowledge candidate line {line_number}"
            ) from exc
        candidates.append(candidate)
    ids = [candidate.candidate_id for candidate in candidates]
    if len(ids) != len(set(ids)):
        raise KnowledgeAuditError(
            "knowledge candidates contain duplicate IDs"
        )
    return tuple(candidates)


def _scope_allows(review: GeneralKnowledgeReview) -> bool:
    allowed_decisions = {
        "general": {"general_answer", "rejected"},
        "medical_boundary": {"escalation_only", "rejected"},
        "product_specific": {
            "product_specific_redirect",
            "rejected",
        },
        "unsupported": {"rejected"},
    }[review.content_scope]
    return review.review_decision in allowed_decisions


def _load_decision_catalog(
    path: Path,
) -> tuple[GeneralKnowledgeDecisionCatalogRow, ...]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise KnowledgeAuditError(
            "knowledge decision catalog is unavailable"
        ) from exc
    if not lines or any(not line for line in lines):
        raise KnowledgeAuditError(
            "knowledge decision catalog is empty or malformed"
        )
    rows: list[GeneralKnowledgeDecisionCatalogRow] = []
    for line_number, line in enumerate(lines, start=1):
        try:
            row = GeneralKnowledgeDecisionCatalogRow.model_validate_json(
                line,
                strict=True,
            )
        except ValueError as exc:
            raise KnowledgeAuditError(
                f"invalid decision catalog line {line_number}"
            ) from exc
        rows.append(row)
    source_paths = [row.source_path for row in rows]
    if len(source_paths) != len(set(source_paths)):
        raise KnowledgeAuditError(
            "decision catalog contains duplicate source paths"
        )
    return tuple(rows)


def materialize_general_knowledge_reviews(
    *,
    candidate_path: Path,
    decision_catalog_path: Path,
    review_dir: Path,
) -> tuple[Path, ...]:
    candidates = _load_candidates(Path(candidate_path))
    catalog = _load_decision_catalog(Path(decision_catalog_path))
    candidates_by_source: dict[
        str,
        list[KnowledgeCandidateBlock],
    ] = {}
    for candidate in candidates:
        candidates_by_source.setdefault(
            candidate.source_path,
            [],
        ).append(candidate)
    catalog_by_source = {
        row.source_path: row
        for row in catalog
    }
    if set(catalog_by_source) != set(candidates_by_source):
        raise KnowledgeAuditError(
            "decision catalog source inventory mismatch"
        )

    destination = Path(review_dir)
    destination.mkdir(parents=True, exist_ok=True)
    expected_names = {
        f"{Path(source_path).stem}.reviews.jsonl"
        for source_path in candidates_by_source
    }
    existing_names = {
        path.name
        for path in destination.glob("*.jsonl")
    }
    if existing_names - expected_names:
        raise KnowledgeAuditError(
            "review directory contains unknown JSONL files"
        )

    output_paths: list[Path] = []
    for source_path in sorted(candidates_by_source):
        source_candidates = sorted(
            candidates_by_source[source_path],
            key=lambda item: item.section_order,
        )
        row = catalog_by_source[source_path]
        if len(row.dispositions) != len(source_candidates):
            raise KnowledgeAuditError(
                "manual disposition count does not match candidates"
            )
        review_rows: list[dict[str, object]] = []
        for candidate, disposition in zip(
            source_candidates,
            row.dispositions,
            strict=True,
        ):
            policy = _DISPOSITION_POLICY[disposition]
            payload = {
                "candidate_id": candidate.candidate_id,
                "source_sha256": candidate.source_sha256,
                "block_sha256": candidate.block_sha256,
                "content_scope": policy["content_scope"],
                "review_decision": policy["review_decision"],
                "allowed_uses": policy["allowed_uses"],
                "forbidden_uses": list(
                    _MANDATORY_FORBIDDEN_USES
                ),
                "review_rationale": policy["review_rationale"],
            }
            review = GeneralKnowledgeReview.model_validate(
                payload,
                strict=True,
            )
            serialized = review.model_dump(mode="json")
            serialized["allowed_uses"] = sorted(
                review.allowed_uses
            )
            serialized["forbidden_uses"] = sorted(
                review.forbidden_uses
            )
            review_rows.append(serialized)
        output_path = (
            destination
            / f"{Path(source_path).stem}.reviews.jsonl"
        )
        output_path.write_text(
            "".join(
                json.dumps(
                    review,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
                for review in review_rows
            ),
            encoding="utf-8",
        )
        output_paths.append(output_path)
    return tuple(output_paths)


def _build_block(
    candidate: KnowledgeCandidateBlock,
    review: GeneralKnowledgeReview,
) -> GeneralKnowledgeBlock:
    return GeneralKnowledgeBlock.model_validate(
        {
            "knowledge_id": candidate.candidate_id,
            "document_id": candidate.document_id,
            "title": candidate.title,
            "section_title": candidate.section_title,
            "exact_text": candidate.exact_text,
            "source_path": candidate.source_path,
            "source_sha256": candidate.source_sha256,
            "block_sha256": candidate.block_sha256,
            "section_order": candidate.section_order,
            "review_decision": review.review_decision,
            "allowed_uses": sorted(review.allowed_uses),
            "forbidden_uses": sorted(review.forbidden_uses),
            "review_rationale": review.review_rationale,
            "retrieval_terms": candidate.retrieval_terms,
        },
        strict=True,
    )


def audit_general_knowledge(
    *,
    candidate_path: Path,
    review_paths: Sequence[Path],
) -> GeneralKnowledgeAudit:
    if (
        isinstance(review_paths, (str, bytes))
        or not isinstance(review_paths, Sequence)
    ):
        raise TypeError("review paths must be a sequence")
    candidates = _load_candidates(Path(candidate_path))
    by_id = {
        candidate.candidate_id: candidate
        for candidate in candidates
    }
    accepted_reviews: dict[str, GeneralKnowledgeReview] = {}
    reviewed_ids: set[str] = set()
    permission_mismatches = 0
    invalid_reviews = 0
    duplicate_reviews = 0
    unknown_reviews = 0
    source_mismatches = 0

    for review_path in sorted(
        (Path(path) for path in review_paths),
        key=lambda path: path.as_posix(),
    ):
        try:
            lines = review_path.read_text(
                encoding="utf-8"
            ).splitlines()
        except (OSError, UnicodeDecodeError) as exc:
            raise KnowledgeAuditError(
                "knowledge review file is unavailable"
            ) from exc
        for line in lines:
            if not line:
                invalid_reviews += 1
                continue
            try:
                review = GeneralKnowledgeReview.model_validate_json(
                    line,
                    strict=True,
                )
            except ValueError:
                invalid_reviews += 1
                continue
            candidate = by_id.get(review.candidate_id)
            if candidate is None:
                unknown_reviews += 1
                continue
            if review.candidate_id in reviewed_ids:
                duplicate_reviews += 1
                continue
            if (
                review.source_sha256 != candidate.source_sha256
                or review.block_sha256 != candidate.block_sha256
            ):
                source_mismatches += 1
                continue
            reviewed_ids.add(review.candidate_id)
            if not _scope_allows(review):
                permission_mismatches += 1
                continue
            try:
                _build_block(candidate, review)
            except ValueError:
                permission_mismatches += 1
                continue
            accepted_reviews[review.candidate_id] = review

    blocks = tuple(
        _build_block(candidate, accepted_reviews[candidate.candidate_id])
        for candidate in candidates
        if candidate.candidate_id in accepted_reviews
    )
    decision_counts = {
        decision: sum(
            block.review_decision == decision
            for block in blocks
        )
        for decision in (
            "general_answer",
            "escalation_only",
            "product_specific_redirect",
            "rejected",
        )
    }
    missing_total = len(candidates) - len(reviewed_ids)
    clean = (
        missing_total == 0
        and permission_mismatches == 0
        and invalid_reviews == 0
        and duplicate_reviews == 0
        and unknown_reviews == 0
        and source_mismatches == 0
        and len(blocks) == len(candidates)
    )
    report = GeneralKnowledgeAuditReport(
        candidate_total=len(candidates),
        reviewed_total=len(reviewed_ids),
        missing_total=missing_total,
        general_answer=decision_counts["general_answer"],
        escalation_only=decision_counts["escalation_only"],
        product_specific_redirect=decision_counts[
            "product_specific_redirect"
        ],
        rejected=decision_counts["rejected"],
        permission_mismatches=permission_mismatches,
        invalid_reviews=invalid_reviews,
        duplicate_reviews=duplicate_reviews,
        unknown_reviews=unknown_reviews,
        source_mismatches=source_mismatches,
        clean=clean,
    )
    return GeneralKnowledgeAudit(
        report=report,
        blocks=blocks,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Audit Guide general-knowledge review coverage.",
    )
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--review-dir", type=Path, required=True)
    parser.add_argument("--require-clean", action="store_true")
    args = parser.parse_args(argv)
    audit = audit_general_knowledge(
        candidate_path=args.candidate,
        review_paths=tuple(args.review_dir.glob("*.jsonl")),
    )
    print(
        json.dumps(
            audit.report.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return int(args.require_clean and not audit.report.clean)


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "GeneralKnowledgeAudit",
    "GeneralKnowledgeAuditReport",
    "GeneralKnowledgeDecisionCatalogRow",
    "GeneralKnowledgeReview",
    "KnowledgeAuditError",
    "ManualDisposition",
    "ReviewContentScope",
    "audit_general_knowledge",
    "main",
    "materialize_general_knowledge_reviews",
]
