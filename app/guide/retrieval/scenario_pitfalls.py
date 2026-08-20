from __future__ import annotations

import re

from app.guide.retrieval.pitfall_contracts import (
    PitfallClaimKind,
    PitfallSeverity,
    TypedPitfall,
)
from app.guide.retrieval.scenario_contracts import (
    ScenarioEvidenceRecord,
    ScenarioEvidenceState,
)


_SENSITIVE_REQUIREMENT = (
    "scenario-v1:sensitive_period:suitable_skin"
)
_SENSITIVE_MARKERS = ("敏感肌", "敏感性肤质", "敏皮", "油敏")
_SAFE_SOURCE_REF = re.compile(r"^[A-Za-z0-9._:-]+$")


def project_scenario_pitfalls(
    records: list[ScenarioEvidenceRecord],
) -> list[TypedPitfall]:
    pitfalls: list[TypedPitfall] = []
    seen_product_ids: set[int] = set()

    for record in records:
        if (
            record.requirement_id != _SENSITIVE_REQUIREMENT
            or record.state is not ScenarioEvidenceState.KNOWN
            or record.product_id in seen_product_ids
        ):
            continue
        label = _skin_label(record.value)
        if label is None or any(
            marker in label for marker in _SENSITIVE_MARKERS
        ):
            continue
        if not record.source_refs or any(
            _SAFE_SOURCE_REF.fullmatch(reference) is None
            for reference in record.source_refs
        ):
            continue

        seen_product_ids.add(record.product_id)
        pitfalls.append(
            TypedPitfall(
                finding_id=(
                    "pitfall-v1:suitability:"
                    f"sensitive_period_{record.product_id}"
                ),
                product_id=record.product_id,
                severity=PitfallSeverity.MEDIUM,
                claim_kind=PitfallClaimKind.SUITABILITY,
                title="敏感期适配证据不足",
                description=(
                    f"现有审核适用肤质仅标注“{label}”，"
                    "不能据此确认敏感期适配或安全性。"
                ),
                evidence_refs=[
                    (
                        "pitfall_evidence:canonical:"
                        f"{record.product_id}:{reference}"
                    )
                    for reference in record.source_refs
                ],
            )
        )

    return pitfalls


def _skin_label(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    if (
        isinstance(value, list)
        and value
        and all(isinstance(item, str) and item.strip() for item in value)
    ):
        return "、".join(item.strip() for item in value)
    return None
