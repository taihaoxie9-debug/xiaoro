from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SelectionConceptAuditError(RuntimeError):
    pass


class SelectionConceptDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    product_id: int = Field(gt=0)
    subject_scope: Literal[
        "exact_product",
        "exact_variant",
        "bundle",
        "brand",
    ]
    variant_scope: str | None = Field(
        default=None,
        min_length=1,
        max_length=160,
    )
    field_key: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    old_value: str = Field(min_length=1, max_length=128)
    decision: Literal[
        "keep_closed_enum",
        "normalize",
        "drop_ordinary_duplicate",
    ]
    new_field_key: str | None = Field(
        default=None,
        pattern=r"^[a-z][a-z0-9_]{1,63}$",
    )
    new_value: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
    )
    rationale: str = Field(min_length=1, max_length=512)

    @model_validator(mode="after")
    def validate_decision(self) -> Self:
        if (
            self.subject_scope == "exact_variant"
            and self.variant_scope is None
        ):
            raise ValueError("exact variant concept requires variant scope")
        if self.decision == "drop_ordinary_duplicate":
            if self.new_field_key is not None or self.new_value is not None:
                raise ValueError("dropped concept forbids replacement")
            return self
        if self.new_field_key is None or self.new_value is None:
            raise ValueError("retained concept requires replacement identity")
        if self.decision == "keep_closed_enum" and (
            self.new_field_key != self.field_key
            or self.new_value != self.old_value
        ):
            raise ValueError("closed enum decision must keep identity")
        return self

    @property
    def key(self) -> tuple[object, ...]:
        return (
            self.product_id,
            self.subject_scope,
            self.variant_scope,
            self.field_key,
            self.old_value,
        )


class SelectionConceptAudit:
    def __init__(
        self,
        *,
        decisions: tuple[SelectionConceptDecision, ...],
        sha256: str,
    ) -> None:
        by_key = {item.key: item for item in decisions}
        if len(by_key) != len(decisions):
            raise SelectionConceptAuditError(
                "selection concept audit contains duplicate identities"
            )
        self._decisions = by_key
        self.sha256 = sha256

    def decision(
        self,
        *,
        product_id: int,
        subject_scope: str,
        variant_scope: str | None,
        field_key: str,
        value: str,
    ) -> SelectionConceptDecision | None:
        return self._decisions.get(
            (
                product_id,
                subject_scope,
                variant_scope,
                field_key,
                value,
            )
        )


def load_selection_concept_audit(
    path: str | Path | None,
) -> SelectionConceptAudit | None:
    if path is None:
        return None
    audit_path = Path(path)
    try:
        content = audit_path.read_bytes()
    except OSError as exc:
        raise SelectionConceptAuditError(
            "selection concept audit is unavailable"
        ) from exc
    decisions: list[SelectionConceptDecision] = []
    for line_number, raw_line in enumerate(
        content.decode("utf-8").splitlines(),
        start=1,
    ):
        if not raw_line:
            continue
        try:
            decisions.append(
                SelectionConceptDecision.model_validate_json(
                    raw_line,
                    strict=True,
                )
            )
        except ValueError as exc:
            raise SelectionConceptAuditError(
                f"invalid selection concept audit line {line_number}"
            ) from exc
    if not decisions:
        raise SelectionConceptAuditError(
            "selection concept audit is empty"
        )
    return SelectionConceptAudit(
        decisions=tuple(decisions),
        sha256=hashlib.sha256(content).hexdigest(),
    )


def project_merchant_identity(
    *,
    audit: SelectionConceptAudit | None,
    product_id: int,
    field_key: str,
    value: str,
) -> tuple[str, str] | None:
    if audit is None:
        return field_key, value
    decision = audit.decision(
        product_id=product_id,
        subject_scope="exact_product",
        variant_scope=None,
        field_key=field_key,
        value=value,
    )
    if decision is None or decision.decision == "keep_closed_enum":
        return field_key, value
    if decision.decision == "drop_ordinary_duplicate":
        return None
    assert decision.new_field_key is not None
    assert decision.new_value is not None
    return decision.new_field_key, decision.new_value


def project_evidence_selection_review(
    *,
    audit: SelectionConceptAudit | None,
    product_id: int,
    subject_scope: str,
    variant_scope: str | None,
    selection_review: object,
) -> object:
    if audit is None or not isinstance(selection_review, dict):
        return selection_review
    raw_projections = selection_review.get("projections")
    if not isinstance(raw_projections, list):
        return selection_review
    projected: list[dict[str, object]] = []
    positions: dict[tuple[str, str], int] = {}
    for raw_projection in raw_projections:
        if not isinstance(raw_projection, dict):
            projected.append(raw_projection)
            continue
        projection = dict(raw_projection)
        field_key = projection.get("field_key")
        value = projection.get("normalized_value")
        if isinstance(field_key, str) and isinstance(value, str):
            decision = audit.decision(
                product_id=product_id,
                subject_scope=subject_scope,
                variant_scope=variant_scope,
                field_key=field_key,
                value=value,
            )
            if decision is not None:
                if decision.decision == "drop_ordinary_duplicate":
                    continue
                assert decision.new_field_key is not None
                assert decision.new_value is not None
                projection["field_key"] = decision.new_field_key
                projection["normalized_value"] = decision.new_value
        key = (
            str(projection.get("field_key")),
            str(projection.get("normalized_value")).casefold(),
        )
        previous_position = positions.get(key)
        if previous_position is None:
            positions[key] = len(projected)
            projected.append(projection)
            continue
        projected[previous_position] = _merge_projection(
            projected[previous_position],
            projection,
        )
    normalized = dict(selection_review)
    normalized["projections"] = projected
    return normalized


def _merge_projection(
    left: dict[str, object],
    right: dict[str, object],
) -> dict[str, object]:
    merged = dict(left)
    left_capabilities = left.get("capabilities", [])
    right_capabilities = right.get("capabilities", [])
    if isinstance(left_capabilities, list) and isinstance(
        right_capabilities,
        list,
    ):
        merged["capabilities"] = sorted(
            {
                *left_capabilities,
                *right_capabilities,
            }
        )
    strengths = [
        value
        for value in (
            left.get("rank_strength"),
            right.get("rank_strength"),
        )
        if isinstance(value, int) and not isinstance(value, bool)
    ]
    merged["rank_strength"] = max(strengths) if strengths else None
    roles = {
        value
        for value in (
            left.get("safety_role"),
            right.get("safety_role"),
        )
        if isinstance(value, str)
    }
    merged["safety_role"] = (
        "verified_warning"
        if "verified_warning" in roles
        else (
            "ordinary"
            if "ordinary" in roles
            else "merchant_positive_safety"
        )
    )
    return merged


__all__ = [
    "SelectionConceptAudit",
    "SelectionConceptAuditError",
    "SelectionConceptDecision",
    "load_selection_concept_audit",
    "project_evidence_selection_review",
    "project_merchant_identity",
]
