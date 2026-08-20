from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from typing import Any


def pitfall_api():
    from app.guide.retrieval.pitfall_contracts import (
        ApprovedPitfallEvidenceRef,
        PitfallClaimKind,
        PitfallEvidenceState,
        PitfallFinding,
        PitfallSeverity,
    )
    from app.guide.retrieval.pitfall_evidence import build_pitfalls

    return (
        ApprovedPitfallEvidenceRef,
        PitfallClaimKind,
        PitfallEvidenceState,
        PitfallFinding,
        PitfallSeverity,
        build_pitfalls,
    )


def test_pitfalls_keep_typed_severity_and_product_owned_evidence_refs() -> None:
    (
        ApprovedEvidence,
        ClaimKind,
        EvidenceState,
        Finding,
        Severity,
        build_pitfalls,
    ) = pitfall_api()
    evidence = [
        _evidence(
            ApprovedEvidence,
            evidence_ref="pitfall_evidence:canonical:501:usage",
            product_id=501,
            content="产品包装要求使用后彻底冲洗。",
        ),
        _evidence(
            ApprovedEvidence,
            evidence_ref="pitfall_evidence:canonical:501:compatibility",
            product_id=501,
            content="审核事实记录了避免同一时段叠加的用法。",
        ),
        _evidence(
            ApprovedEvidence,
            evidence_ref="pitfall_evidence:canonical:501:suitability",
            product_id=501,
            content="审核事实记录了特定肤质的使用限制。",
        ),
    ]
    findings = [
        _finding(
            Finding,
            product_id=501,
            finding_id="pitfall-v1:suitability:dryness",
            severity=Severity.LOW,
            claim_kind=ClaimKind.SUITABILITY,
            state=EvidenceState.KNOWN,
            title="留意干燥感",
            description="特定肤质使用时留意干燥感。",
            evidence_refs=[
                "pitfall_evidence:canonical:501:suitability"
            ],
        ),
        _finding(
            Finding,
            product_id=501,
            finding_id="pitfall-v1:usage:rinse",
            severity=Severity.HIGH,
            claim_kind=ClaimKind.USAGE,
            state=EvidenceState.KNOWN,
            title="按包装要求冲洗",
            description="使用后按包装要求彻底冲洗。",
            evidence_refs=["pitfall_evidence:canonical:501:usage"],
        ),
        _finding(
            Finding,
            product_id=501,
            finding_id="pitfall-v1:compatibility:layering",
            severity=Severity.MEDIUM,
            claim_kind=ClaimKind.COMPATIBILITY,
            state=EvidenceState.KNOWN,
            title="避免同一时段叠加",
            description="按审核用法错开使用时段。",
            evidence_refs=[
                "pitfall_evidence:canonical:501:compatibility"
            ],
        ),
    ]

    result = build_pitfalls(
        product_id=501,
        findings=findings,
        approved_evidence=evidence,
    )

    assert [item.severity for item in result] == [
        Severity.HIGH,
        Severity.MEDIUM,
        Severity.LOW,
    ]
    assert [item.finding_id for item in result] == [
        "pitfall-v1:usage:rinse",
        "pitfall-v1:compatibility:layering",
        "pitfall-v1:suitability:dryness",
    ]
    assert all(item.product_id == 501 for item in result)
    assert result[0].evidence_refs == [
        "pitfall_evidence:canonical:501:usage"
    ]
    assert {"high", "medium", "low"} == {
        item.value for item in Severity
    }


def test_duplicate_findings_and_refs_have_stable_order() -> None:
    (
        ApprovedEvidence,
        ClaimKind,
        EvidenceState,
        Finding,
        Severity,
        build_pitfalls,
    ) = pitfall_api()
    first_ref = _evidence(
        ApprovedEvidence,
        evidence_ref="pitfall_evidence:canonical:501:usage:a",
        product_id=501,
        content="第一条审核用法事实。",
    )
    second_ref = _evidence(
        ApprovedEvidence,
        evidence_ref="pitfall_evidence:canonical:501:usage:b",
        product_id=501,
        content="第二条审核用法事实。",
    )
    first_finding = _finding(
        Finding,
        product_id=501,
        finding_id="pitfall-v1:usage:rinse",
        severity=Severity.MEDIUM,
        claim_kind=ClaimKind.USAGE,
        state=EvidenceState.KNOWN,
        title="按说明冲洗",
        description="使用后按说明冲洗。",
        evidence_refs=[first_ref.evidence_ref],
    )
    second_finding = first_finding.model_copy(
        update={"evidence_refs": [second_ref.evidence_ref]},
        deep=True,
    )

    outputs = [
        build_pitfalls(
            product_id=501,
            findings=findings,
            approved_evidence=evidence,
        )
        for findings, evidence in (
            (
                [second_finding, first_finding, first_finding],
                [second_ref, first_ref, first_ref],
            ),
            (
                [first_finding, second_finding, second_finding],
                [first_ref, second_ref, second_ref],
            ),
        )
    ]

    assert outputs[0] == outputs[1]
    assert len(outputs[0]) == 1
    assert outputs[0][0].evidence_refs == [
        first_ref.evidence_ref,
        second_ref.evidence_ref,
    ]


def test_unknown_and_absent_facts_emit_no_conclusion() -> None:
    (
        _,
        ClaimKind,
        EvidenceState,
        Finding,
        Severity,
        build_pitfalls,
    ) = pitfall_api()
    unresolved = [
        _finding(
            Finding,
            product_id=501,
            finding_id="pitfall-v1:safety:unknown",
            severity=Severity.HIGH,
            claim_kind=ClaimKind.SAFETY,
            state=EvidenceState.UNKNOWN,
        ),
        _finding(
            Finding,
            product_id=501,
            finding_id="pitfall-v1:safety:absent",
            severity=Severity.HIGH,
            claim_kind=ClaimKind.SAFETY,
            state=EvidenceState.ABSENT,
        ),
    ]

    assert build_pitfalls(
        product_id=501,
        findings=unresolved,
        approved_evidence=[],
    ) == []


def test_conflicting_fact_fails_closed_without_partial_pitfalls() -> None:
    (
        ApprovedEvidence,
        ClaimKind,
        EvidenceState,
        Finding,
        Severity,
        build_pitfalls,
    ) = pitfall_api()
    valid_ref = _evidence(
        ApprovedEvidence,
        evidence_ref="pitfall_evidence:canonical:501:usage",
        product_id=501,
        content="审核用法事实。",
    )
    findings = [
        _finding(
            Finding,
            product_id=501,
            finding_id="pitfall-v1:usage:valid",
            severity=Severity.MEDIUM,
            claim_kind=ClaimKind.USAGE,
            state=EvidenceState.KNOWN,
            title="按说明使用",
            description="按照已审核说明使用。",
            evidence_refs=[valid_ref.evidence_ref],
        ),
        _finding(
            Finding,
            product_id=501,
            finding_id="pitfall-v1:safety:conflict",
            severity=Severity.HIGH,
            claim_kind=ClaimKind.SAFETY,
            state=EvidenceState.CONFLICT,
            evidence_refs=[valid_ref.evidence_ref],
        ),
    ]

    assert build_pitfalls(
        product_id=501,
        findings=findings,
        approved_evidence=[valid_ref],
    ) == []


def test_foreign_or_unknown_evidence_ref_fails_closed() -> None:
    (
        ApprovedEvidence,
        ClaimKind,
        EvidenceState,
        Finding,
        Severity,
        build_pitfalls,
    ) = pitfall_api()
    foreign_ref = _evidence(
        ApprovedEvidence,
        evidence_ref="pitfall_evidence:canonical:502:usage",
        product_id=502,
        content="另一个商品的审核用法事实。",
    )

    for evidence_refs, approved_evidence in (
        ([foreign_ref.evidence_ref], [foreign_ref]),
        (["pitfall_evidence:canonical:501:missing"], []),
    ):
        finding = _finding(
            Finding,
            product_id=501,
            finding_id="pitfall-v1:usage:unowned",
            severity=Severity.HIGH,
            claim_kind=ClaimKind.USAGE,
            state=EvidenceState.KNOWN,
            title="不能发布的提示",
            description="这条提示没有当前商品拥有的证据。",
            evidence_refs=evidence_refs,
        )

        assert build_pitfalls(
            product_id=501,
            findings=[finding],
            approved_evidence=approved_evidence,
        ) == []


def test_review_evidence_cannot_authorize_a_safety_conclusion() -> None:
    (
        ApprovedEvidence,
        ClaimKind,
        EvidenceState,
        Finding,
        Severity,
        build_pitfalls,
    ) = pitfall_api()
    review_ref = _evidence(
        ApprovedEvidence,
        evidence_ref="pitfall_evidence:review:501:consumer-a",
        product_id=501,
        content="消费者表示自己使用时没有不适。",
        source_kind="approved_review_evidence",
    )
    finding = _finding(
        Finding,
        product_id=501,
        finding_id="pitfall-v1:safety:consumer-claim",
        severity=Severity.LOW,
        claim_kind=ClaimKind.SAFETY,
        state=EvidenceState.KNOWN,
        title="不能推导安全结论",
        description="消费者体验不能证明产品安全。",
        evidence_refs=[review_ref.evidence_ref],
    )

    assert build_pitfalls(
        product_id=501,
        findings=[finding],
        approved_evidence=[review_ref],
    ) == []


def test_conflicting_evidence_ref_or_finding_id_fails_closed() -> None:
    (
        ApprovedEvidence,
        ClaimKind,
        EvidenceState,
        Finding,
        Severity,
        build_pitfalls,
    ) = pitfall_api()
    first_ref = _evidence(
        ApprovedEvidence,
        evidence_ref="pitfall_evidence:canonical:501:usage",
        product_id=501,
        content="第一版审核事实。",
    )
    changed_ref = _evidence(
        ApprovedEvidence,
        evidence_ref=first_ref.evidence_ref,
        product_id=501,
        content="同一证据引用下被替换的事实。",
    )
    first_finding = _finding(
        Finding,
        product_id=501,
        finding_id="pitfall-v1:usage:rinse",
        severity=Severity.MEDIUM,
        claim_kind=ClaimKind.USAGE,
        state=EvidenceState.KNOWN,
        title="第一版提示",
        description="第一版描述。",
        evidence_refs=[first_ref.evidence_ref],
    )
    changed_finding = first_finding.model_copy(
        update={"description": "同一 finding ID 下被替换的描述。"},
        deep=True,
    )

    assert build_pitfalls(
        product_id=501,
        findings=[first_finding],
        approved_evidence=[first_ref, changed_ref],
    ) == []
    assert build_pitfalls(
        product_id=501,
        findings=[first_finding, changed_finding],
        approved_evidence=[first_ref],
    ) == []


def test_pitfall_contract_has_no_ranking_or_winner_authority() -> None:
    (
        ApprovedEvidence,
        ClaimKind,
        EvidenceState,
        Finding,
        Severity,
        build_pitfalls,
    ) = pitfall_api()
    evidence = _evidence(
        ApprovedEvidence,
        evidence_ref="pitfall_evidence:canonical:501:usage",
        product_id=501,
        content="审核用法事实。",
    )
    finding = _finding(
        Finding,
        product_id=501,
        finding_id="pitfall-v1:usage:rinse",
        severity=Severity.MEDIUM,
        claim_kind=ClaimKind.USAGE,
        state=EvidenceState.KNOWN,
        title="按说明使用",
        description="按照审核用法使用。",
        evidence_refs=[evidence.evidence_ref],
    )

    result = build_pitfalls(
        product_id=501,
        findings=[finding],
        approved_evidence=[evidence],
    )
    forbidden_keys = {
        "score",
        "winner",
        "winner_product_id",
        "ordered_product_ids",
        "is_safe",
    }

    assert forbidden_keys.isdisjoint(_all_keys(result[0].model_dump()))


def _evidence(
    model,
    *,
    evidence_ref: str,
    product_id: int,
    content: str,
    source_kind: str = "canonical_reviewed_fact",
):
    return model(
        evidence_ref=evidence_ref,
        product_id=product_id,
        source_kind=source_kind,
        source_locator=(
            f"urn:xiaoro:pitfall-evidence:{product_id}:{evidence_ref}"
        ),
        content=content,
        content_sha256=sha256(content.encode("utf-8")).hexdigest(),
        approved_at=datetime(2026, 8, 9, 4, 0, tzinfo=UTC),
        approval_version="phase2-pitfall-review-v1",
    )


def _finding(
    model,
    *,
    product_id: int,
    finding_id: str,
    severity,
    claim_kind,
    state,
    title: str | None = None,
    description: str | None = None,
    evidence_refs: list[str] | None = None,
):
    return model(
        finding_id=finding_id,
        product_id=product_id,
        severity=severity,
        claim_kind=claim_kind,
        evidence_state=state,
        title=title,
        description=description,
        evidence_refs=evidence_refs or [],
    )


def _all_keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {
            key
            for item in value.values()
            for key in _all_keys(item)
        }
    if isinstance(value, list):
        return {
            key
            for item in value
            for key in _all_keys(item)
        }
    return set()
