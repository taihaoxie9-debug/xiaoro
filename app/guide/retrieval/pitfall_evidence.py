from __future__ import annotations

from collections.abc import Iterable

from app.guide.retrieval.pitfall_contracts import (
    ApprovedPitfallEvidenceRef,
    PitfallClaimKind,
    PitfallEvidenceState,
    PitfallFinding,
    PitfallSeverity,
    TypedPitfall,
)


_SEVERITY_ORDER = {
    PitfallSeverity.HIGH: 0,
    PitfallSeverity.MEDIUM: 1,
    PitfallSeverity.LOW: 2,
}


def build_pitfalls(
    *,
    product_id: int,
    findings: Iterable[PitfallFinding],
    approved_evidence: Iterable[ApprovedPitfallEvidenceRef],
) -> list[TypedPitfall]:
    evidence_by_ref = _index_evidence(approved_evidence)
    if evidence_by_ref is None:
        return []

    findings_by_id = _index_findings(
        product_id=product_id,
        findings=findings,
    )
    if findings_by_id is None:
        return []
    if any(
        item.evidence_state is PitfallEvidenceState.CONFLICT
        for item in findings_by_id.values()
    ):
        return []

    pitfalls: list[TypedPitfall] = []
    for finding in findings_by_id.values():
        if finding.evidence_state is not PitfallEvidenceState.KNOWN:
            continue

        owned_evidence = []
        for evidence_ref in finding.evidence_refs:
            evidence = evidence_by_ref.get(evidence_ref)
            if evidence is None or evidence.product_id != product_id:
                return []
            owned_evidence.append(evidence)

        if (
            finding.claim_kind is PitfallClaimKind.SAFETY
            and any(
                item.source_kind != "canonical_reviewed_fact"
                for item in owned_evidence
            )
        ):
            return []

        if finding.title is None or finding.description is None:
            return []
        pitfalls.append(
            TypedPitfall(
                finding_id=finding.finding_id,
                product_id=finding.product_id,
                severity=finding.severity,
                claim_kind=finding.claim_kind,
                title=finding.title,
                description=finding.description,
                evidence_refs=list(finding.evidence_refs),
            )
        )

    return sorted(
        pitfalls,
        key=lambda item: (
            _SEVERITY_ORDER[item.severity],
            item.finding_id,
        ),
    )


def _index_evidence(
    evidence: Iterable[ApprovedPitfallEvidenceRef],
) -> dict[str, ApprovedPitfallEvidenceRef] | None:
    by_ref: dict[str, ApprovedPitfallEvidenceRef] = {}
    for item in evidence:
        stored = item.model_copy(deep=True)
        existing = by_ref.get(stored.evidence_ref)
        if existing is None:
            by_ref[stored.evidence_ref] = stored
        elif existing != stored:
            return None
    return by_ref


def _index_findings(
    *,
    product_id: int,
    findings: Iterable[PitfallFinding],
) -> dict[str, PitfallFinding] | None:
    by_id: dict[str, PitfallFinding] = {}
    for item in findings:
        stored = item.model_copy(
            update={
                "evidence_refs": sorted(set(item.evidence_refs)),
            },
            deep=True,
        )
        if stored.product_id != product_id:
            return None

        existing = by_id.get(stored.finding_id)
        if existing is None:
            by_id[stored.finding_id] = stored
            continue
        if _finding_claim(existing) != _finding_claim(stored):
            return None
        by_id[stored.finding_id] = existing.model_copy(
            update={
                "evidence_refs": sorted(
                    {
                        *existing.evidence_refs,
                        *stored.evidence_refs,
                    }
                )
            },
            deep=True,
        )
    return by_id


def _finding_claim(finding: PitfallFinding) -> tuple[object, ...]:
    return (
        finding.product_id,
        finding.severity,
        finding.claim_kind,
        finding.evidence_state,
        finding.title,
        finding.description,
    )
