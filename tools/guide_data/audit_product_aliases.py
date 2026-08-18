from __future__ import annotations

import argparse
import ast
from collections.abc import Sequence
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Literal, Self
import unicodedata

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


AliasDiscoverySource = Literal[
    "evidence",
    "canonical_name",
    "legacy_intent",
    "legacy_agent",
    "legacy_v2",
]
AliasDisposition = Literal[
    "approved_exact_product",
    "approved_exact_variant",
    "ambiguous_family",
    "marketing_phrase",
    "ingredient_nickname",
    "unavailable_product",
    "unresolved_candidate",
]

_ALIAS_MAP_NAMES = frozenset({
    "PRODUCT_ALIAS_MAP",
    "alias_map",
    "product_aliases",
})
_ALIAS_EVIDENCE_TERM = re.compile(r"昵称|别称|俗称|又称")
_ALIAS_RELATION_TERM = re.compile(r"alias|nickname|name_explanation")


class ProductAliasAuditError(ValueError):
    pass


class _StrictFrozenModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
        protected_namespaces=(),
    )


class ProductAliasReviewRecord(_StrictFrozenModel):
    alias: str = Field(min_length=2, max_length=160)
    discovery_sources: tuple[AliasDiscoverySource, ...] = Field(
        min_length=1,
        max_length=8,
    )
    candidate_product_ids: tuple[int, ...] = Field(max_length=16)
    evidence_ids: tuple[str, ...] = Field(max_length=32)
    clarify_terms: tuple[str, ...] = Field(
        default_factory=tuple,
        max_length=32,
    )
    disposition: AliasDisposition
    product_id: int | None = Field(default=None, gt=0)
    variant_scope: str | None = Field(
        default=None,
        min_length=1,
        max_length=160,
    )
    review_rationale: str = Field(min_length=1, max_length=1000)

    @field_validator(
        "discovery_sources",
        "candidate_product_ids",
        "evidence_ids",
        "clarify_terms",
        mode="before",
    )
    @classmethod
    def freeze_sequences(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @model_validator(mode="after")
    def validate_review_shape(self) -> Self:
        if self.alias != self.alias.strip():
            raise ValueError("product alias review surface must be trimmed")
        if self.review_rationale != self.review_rationale.strip():
            raise ValueError("product alias review rationale must be trimmed")
        if len(self.discovery_sources) != len(set(self.discovery_sources)):
            raise ValueError("product alias discovery sources must be unique")
        if (
            len(self.candidate_product_ids)
            != len(set(self.candidate_product_ids))
            or any(product_id <= 0 for product_id in self.candidate_product_ids)
        ):
            raise ValueError(
                "candidate product IDs must be unique positive integers"
            )
        if len(self.evidence_ids) != len(set(self.evidence_ids)):
            raise ValueError("product alias evidence IDs must be unique")
        if (
            len(self.clarify_terms) != len(set(self.clarify_terms))
            or any(
                not term or term != term.strip()
                for term in self.clarify_terms
            )
        ):
            raise ValueError(
                "product alias clarification terms must be unique and trimmed"
            )
        if any(
            len(evidence_id) != 64
            or any(
                character not in "0123456789abcdef"
                for character in evidence_id
            )
            for evidence_id in self.evidence_ids
        ):
            raise ValueError("product alias evidence IDs must be SHA256 IDs")

        if self.disposition == "approved_exact_product":
            if self.product_id is None or self.variant_scope is not None:
                raise ValueError(
                    "exact product aliases require one product and no variant"
                )
        elif self.disposition == "approved_exact_variant":
            if self.product_id is None or self.variant_scope is None:
                raise ValueError(
                    "exact variant aliases require product and variant scope"
                )
            if not self.evidence_ids:
                raise ValueError(
                    "exact variant aliases require reviewed evidence"
                )
        elif self.disposition == "ambiguous_family":
            if (
                self.product_id is not None
                or self.variant_scope is not None
                or len(self.candidate_product_ids) < 2
                or self.clarify_terms
            ):
                raise ValueError(
                    "ambiguous aliases require multiple candidates and no "
                    "default product"
                )
        elif self.product_id is not None or self.variant_scope is not None:
            raise ValueError(
                "non-runtime alias dispositions forbid identity bindings"
            )
        elif self.clarify_terms:
            raise ValueError(
                "non-runtime alias dispositions forbid clarification terms"
            )

        if (
            self.product_id is not None
            and self.product_id not in self.candidate_product_ids
        ):
            raise ValueError(
                "published product must be listed among alias candidates"
            )
        return self

    @property
    def is_runtime_alias(self) -> bool:
        return self.disposition in {
            "approved_exact_product",
            "approved_exact_variant",
            "ambiguous_family",
        }


class LegacyAliasCandidate(_StrictFrozenModel):
    alias: str = Field(min_length=1, max_length=160)
    source_paths: tuple[str, ...] = Field(min_length=1, max_length=8)
    map_names: tuple[str, ...] = Field(min_length=1, max_length=8)


class ProductAliasAuditReport(_StrictFrozenModel):
    canonical_product_count: int = Field(ge=0)
    evidence_alias_block_count: int = Field(ge=0)
    legacy_alias_count: int = Field(ge=0)
    reviewed_alias_count: int = Field(ge=0)
    runtime_alias_count: int = Field(ge=0)
    missing_evidence_reviews: int = Field(ge=0)
    missing_legacy_reviews: int = Field(ge=0)
    unknown_product_bindings: int = Field(ge=0)
    invalid_variant_bindings: int = Field(ge=0)
    invalid_reviews: int = Field(ge=0)
    duplicate_reviews: int = Field(ge=0)
    unknown_evidence_refs: int = Field(ge=0)
    clean: bool


class ProductAliasAudit(_StrictFrozenModel):
    report: ProductAliasAuditReport
    reviews: tuple[ProductAliasReviewRecord, ...]
    legacy_candidates: tuple[LegacyAliasCandidate, ...]
    missing_evidence_ids: tuple[str, ...]
    missing_legacy_aliases: tuple[str, ...]


def normalize_alias(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("product alias must be a string")
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return "".join(normalized.split())


def _load_jsonl(path: Path, *, label: str) -> tuple[dict[str, object], ...]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise ProductAliasAuditError(f"{label} file is unavailable") from exc
    rows: list[dict[str, object]] = []
    for line_number, line in enumerate(lines, start=1):
        if not line:
            continue
        try:
            row = json.loads(line)
        except (json.JSONDecodeError, TypeError) as exc:
            raise ProductAliasAuditError(
                f"invalid {label} JSONL line {line_number}"
            ) from exc
        if not isinstance(row, dict):
            raise ProductAliasAuditError(
                f"invalid {label} JSONL line {line_number}"
            )
        rows.append(row)
    return tuple(rows)


def _load_reviews(
    path: Path,
) -> tuple[tuple[ProductAliasReviewRecord, ...], int]:
    rows = _load_jsonl(path, label="product alias review")
    reviews: list[ProductAliasReviewRecord] = []
    invalid = 0
    for row in rows:
        try:
            reviews.append(
                ProductAliasReviewRecord.model_validate(row, strict=True)
            )
        except ValueError:
            invalid += 1
    return tuple(reviews), invalid


def _is_alias_evidence(row: dict[str, object]) -> bool:
    if row.get("review_status") != "accepted":
        return False
    searchable_parts = [
        row.get("exact_text"),
        row.get("plain_meaning"),
        row.get("review_rationale"),
    ]
    free_descriptors = row.get("free_descriptors")
    if isinstance(free_descriptors, list):
        searchable_parts.extend(free_descriptors)
    qualifiers = row.get("qualifiers")
    if isinstance(qualifiers, dict):
        footnotes = qualifiers.get("footnotes")
        if isinstance(footnotes, list):
            searchable_parts.extend(footnotes)
    searchable = " ".join(
        value for value in searchable_parts if isinstance(value, str)
    )
    if _ALIAS_EVIDENCE_TERM.search(searchable):
        return True
    relations = row.get("relations")
    if not isinstance(relations, list):
        return False
    return any(
        isinstance(relation, dict)
        and isinstance(relation.get("predicate"), str)
        and _ALIAS_RELATION_TERM.search(relation["predicate"])
        for relation in relations
    )


def _assignment_map_name(node: ast.Assign | ast.AnnAssign) -> str | None:
    targets: Sequence[ast.expr]
    if isinstance(node, ast.Assign):
        targets = node.targets
    else:
        targets = (node.target,)
    for target in targets:
        if isinstance(target, ast.Name) and target.id in _ALIAS_MAP_NAMES:
            return target.id
    return None


def discover_legacy_aliases(
    paths: Sequence[Path],
) -> tuple[LegacyAliasCandidate, ...]:
    discovered: dict[str, dict[str, object]] = {}
    for raw_path in paths:
        path = Path(raw_path)
        try:
            tree = ast.parse(
                path.read_text(encoding="utf-8"),
                filename=str(path),
            )
        except (OSError, UnicodeDecodeError, SyntaxError) as exc:
            raise ProductAliasAuditError(
                f"legacy alias source is unavailable: {path}"
            ) from exc
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            map_name = _assignment_map_name(node)
            if map_name is None:
                continue
            value = node.value
            if not isinstance(value, ast.Dict):
                continue
            for key in value.keys:
                if not isinstance(key, ast.Constant) or not isinstance(
                    key.value,
                    str,
                ):
                    continue
                normalized = normalize_alias(key.value)
                if not normalized:
                    continue
                current = discovered.setdefault(
                    normalized,
                    {
                        "alias": key.value,
                        "source_paths": set(),
                        "map_names": set(),
                    },
                )
                current["source_paths"].add(str(path))
                current["map_names"].add(map_name)
    return tuple(
        LegacyAliasCandidate(
            alias=str(value["alias"]),
            source_paths=tuple(sorted(value["source_paths"])),
            map_names=tuple(sorted(value["map_names"])),
        )
        for _, value in sorted(discovered.items())
    )


def audit_product_aliases(
    *,
    canonical_path: Path,
    evidence_path: Path,
    review_path: Path,
    legacy_paths: Sequence[Path] = (),
) -> ProductAliasAudit:
    canonical_rows = _load_jsonl(
        Path(canonical_path),
        label="Canonical product",
    )
    evidence_rows = _load_jsonl(
        Path(evidence_path),
        label="product evidence",
    )
    reviews, invalid_reviews = _load_reviews(Path(review_path))
    canonical_ids = {
        product_id
        for row in canonical_rows
        if isinstance((product_id := row.get("product_id")), int)
        and not isinstance(product_id, bool)
        and product_id > 0
    }
    evidence_by_id = {
        evidence_id: row
        for row in evidence_rows
        if isinstance((evidence_id := row.get("evidence_id")), str)
    }
    alias_evidence_ids = {
        evidence_id
        for evidence_id, row in evidence_by_id.items()
        if _is_alias_evidence(row)
    }

    normalized_reviews: dict[str, ProductAliasReviewRecord] = {}
    duplicate_reviews = 0
    for review in reviews:
        normalized = normalize_alias(review.alias)
        if normalized in normalized_reviews:
            duplicate_reviews += 1
            continue
        normalized_reviews[normalized] = review

    reviewed_evidence_ids = {
        evidence_id
        for review in reviews
        for evidence_id in review.evidence_ids
    }
    missing_evidence_ids = tuple(
        sorted(alias_evidence_ids - reviewed_evidence_ids)
    )
    unknown_evidence_refs = len(
        reviewed_evidence_ids - set(evidence_by_id)
    )

    legacy_candidates = discover_legacy_aliases(legacy_paths)
    missing_legacy_aliases = tuple(
        sorted(
            candidate.alias
            for candidate in legacy_candidates
            if normalize_alias(candidate.alias) not in normalized_reviews
        )
    )

    unknown_product_bindings = 0
    invalid_variant_bindings = 0
    for review in reviews:
        referenced_products = set(review.candidate_product_ids)
        if review.product_id is not None:
            referenced_products.add(review.product_id)
        if not referenced_products.issubset(canonical_ids):
            unknown_product_bindings += 1
        if review.disposition != "approved_exact_variant":
            continue
        matching_variant_evidence = [
            evidence_by_id[evidence_id]
            for evidence_id in review.evidence_ids
            if evidence_id in evidence_by_id
            and evidence_by_id[evidence_id].get("product_id")
            == review.product_id
            and evidence_by_id[evidence_id].get("subject_scope")
            == "exact_variant"
            and evidence_by_id[evidence_id].get("variant_scope")
            == review.variant_scope
        ]
        if not matching_variant_evidence:
            invalid_variant_bindings += 1

    clean = not any((
        missing_evidence_ids,
        missing_legacy_aliases,
        unknown_product_bindings,
        invalid_variant_bindings,
        invalid_reviews,
        duplicate_reviews,
        unknown_evidence_refs,
    ))
    report = ProductAliasAuditReport(
        canonical_product_count=len(canonical_ids),
        evidence_alias_block_count=len(alias_evidence_ids),
        legacy_alias_count=len(legacy_candidates),
        reviewed_alias_count=len(reviews),
        runtime_alias_count=sum(
            review.is_runtime_alias for review in reviews
        ),
        missing_evidence_reviews=len(missing_evidence_ids),
        missing_legacy_reviews=len(missing_legacy_aliases),
        unknown_product_bindings=unknown_product_bindings,
        invalid_variant_bindings=invalid_variant_bindings,
        invalid_reviews=invalid_reviews,
        duplicate_reviews=duplicate_reviews,
        unknown_evidence_refs=unknown_evidence_refs,
        clean=clean,
    )
    return ProductAliasAudit(
        report=report,
        reviews=reviews,
        legacy_candidates=legacy_candidates,
        missing_evidence_ids=missing_evidence_ids,
        missing_legacy_aliases=missing_legacy_aliases,
    )


def publish_controlled_product_aliases(
    *,
    review_path: Path,
    aliases_path: Path,
    manifest_path: Path,
    canonical_sha256: str,
) -> None:
    if (
        len(canonical_sha256) != 64
        or any(
            character not in "0123456789abcdef"
            for character in canonical_sha256
        )
    ):
        raise ValueError("canonical_sha256 must be a lowercase SHA256")
    reviews, invalid_reviews = _load_reviews(Path(review_path))
    if invalid_reviews:
        raise ProductAliasAuditError(
            "cannot publish invalid product alias reviews"
        )
    runtime_reviews = sorted(
        (
            review
            for review in reviews
            if review.is_runtime_alias
        ),
        key=lambda item: (normalize_alias(item.alias), item.alias),
    )
    records: list[dict[str, object]] = []
    for review in runtime_reviews:
        identity_scope = {
            "approved_exact_product": "exact_product",
            "approved_exact_variant": "exact_variant",
            "ambiguous_family": "ambiguous_family",
        }[review.disposition]
        records.append({
            "alias": review.alias,
            "identity_scope": identity_scope,
            "product_ids": list(review.candidate_product_ids),
            "default_product_id": review.product_id,
            "variant_scope": review.variant_scope,
            "clarify_terms": list(review.clarify_terms),
            "source_refs": (
                list(review.evidence_ids)
                if review.evidence_ids
                else [canonical_sha256]
            ),
            "review_status": "approved",
            "review_rationale": review.review_rationale,
        })
    if not records:
        raise ProductAliasAuditError(
            "controlled alias publication must not be empty"
        )
    payload = "".join(
        json.dumps(
            record,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
        for record in records
    ).encode("utf-8")
    aliases_path = Path(aliases_path)
    manifest_path = Path(manifest_path)
    aliases_path.write_bytes(payload)
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "guide-controlled-product-aliases-v1",
                "aliases_file": aliases_path.name,
                "aliases_sha256": sha256(payload).hexdigest(),
                "canonical_sha256": canonical_sha256,
                "record_count": len(records),
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit controlled product aliases",
    )
    parser.add_argument("--canonical", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--reviews", type=Path, required=True)
    parser.add_argument(
        "--legacy",
        type=Path,
        action="append",
        default=[],
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    audit = audit_product_aliases(
        canonical_path=args.canonical,
        evidence_path=args.evidence,
        review_path=args.reviews,
        legacy_paths=tuple(args.legacy),
    )
    print(
        json.dumps(
            audit.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0 if audit.report.clean else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "LegacyAliasCandidate",
    "ProductAliasAudit",
    "ProductAliasAuditError",
    "ProductAliasAuditReport",
    "ProductAliasReviewRecord",
    "audit_product_aliases",
    "discover_legacy_aliases",
    "normalize_alias",
    "publish_controlled_product_aliases",
]
