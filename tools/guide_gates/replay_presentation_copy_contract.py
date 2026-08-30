from __future__ import annotations

import argparse
from collections.abc import Sequence
from hashlib import sha256
import json
from pathlib import Path
import sys
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    model_validator,
)

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.guide.adapters.llm.contracts import SemanticTokenUsage
from app.guide.adapters.llm.presentation_copywriter_adapter import (
    CopywriterCallResult,
)
from app.guide.presentation.contracts import CardDisplayContract
from app.guide.presentation.copywriter_contracts import (
    CopywriterDraft,
    section_copy_blocks_include_winner_claim,
    validate_copy_provenance,
)
from app.guide.presentation.presentation_compiler import (
    PresentationCompileInputs,
    compile_presentation,
)
from app.guide.intent.responsibility_matrix import (
    decision_for_responsibility,
)
from app.guide.presentation.copywriter_validation import (
    CopywriterValidationError,
    validate_copywriter_draft,
)
from tools.guide_gates.presentation_copy_gate import (
    PresentationCopyGateCase,
    load_copy_gate_cases,
)


class _StrictFrozen(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
        protected_namespaces=(),
    )


class ContractReplayRow(_StrictFrozen):
    case_id: str
    classification: Literal[
        "legacy_universal_contract",
        "section_contract",
        "parser_invalid",
        "validation_failure",
    ]
    validation_error_code: str | None = None
    compiler_copy_source: Literal[
        "model",
        "authoritative",
        "fallback",
    ] | None = None
    compiler_fallback_reason: str | None = None

    @model_validator(mode="after")
    def validate_compiler_provenance(self) -> ContractReplayRow:
        if self.compiler_copy_source is None:
            if self.compiler_fallback_reason is not None:
                raise ValueError(
                    "missing compiler source forbids fallback reason"
                )
            return self
        validate_copy_provenance(
            copy_source=self.compiler_copy_source,
            fallback_reason=self.compiler_fallback_reason,
        )
        return self


class ContractReplayReport(_StrictFrozen):
    schema_version: Literal[
        "guide-presentation-copy-contract-replay-v1"
    ] = "guide-presentation-copy-contract-replay-v1"
    source_results_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    cases_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    provider_call_count: Literal[0] = 0
    case_count: int = Field(ge=0)
    legacy_universal_count: int = Field(ge=0)
    section_draft_count: int = Field(ge=0)
    parser_invalid_count: int = Field(ge=0)
    validation_failure_count: int = Field(ge=0)
    rows: tuple[ContractReplayRow, ...]


class _ReplayCopywriter:
    def __init__(self, draft: CopywriterDraft) -> None:
        self._draft = draft

    def write(self, packet) -> CopywriterCallResult:
        del packet
        return CopywriterCallResult(
            draft=self._draft,
            usage=SemanticTokenUsage(
                prompt_tokens=0,
                completion_tokens=0,
                total_tokens=0,
                cached_tokens=0,
            ),
            provider="replay",
            model="replay",
            latency_ms=0.0,
        )


def replay_copywriter_contract_results(
    *,
    cases: Sequence[PresentationCopyGateCase],
    results_path: str | Path,
    output_path: str | Path,
) -> ContractReplayReport:
    normalized_cases = tuple(cases)
    if any(
        not isinstance(case, PresentationCopyGateCase)
        for case in normalized_cases
    ):
        raise TypeError(
            "cases must contain PresentationCopyGateCase values"
        )
    source = Path(results_path)
    source_bytes = source.read_bytes()
    raw_rows = tuple(
        json.loads(line)
        for line in source_bytes.decode("utf-8").splitlines()
        if line.strip()
    )
    expected_ids = tuple(case.case_id for case in normalized_cases)
    actual_ids = tuple(
        row.get("case_id") if isinstance(row, dict) else None
        for row in raw_rows
    )
    if actual_ids != expected_ids:
        raise ValueError(
            "copywriter contract replay identities must exactly match cases"
        )

    rows = tuple(
        _replay_row(case, raw)
        for case, raw in zip(
            normalized_cases,
            raw_rows,
            strict=True,
        )
    )
    report = ContractReplayReport(
        source_results_sha256=sha256(source_bytes).hexdigest(),
        cases_sha256=_cases_sha256(normalized_cases),
        case_count=len(normalized_cases),
        legacy_universal_count=sum(
            row.classification == "legacy_universal_contract"
            for row in rows
        ),
        section_draft_count=sum(
            row.classification == "section_contract"
            for row in rows
        ),
        parser_invalid_count=sum(
            row.classification == "parser_invalid" for row in rows
        ),
        validation_failure_count=sum(
            row.classification == "validation_failure"
            for row in rows
        ),
        rows=rows,
    )
    destination = Path(output_path)
    if destination.exists():
        raise FileExistsError(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(
            report.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )
    return report


def _replay_row(
    case: PresentationCopyGateCase,
    raw: object,
) -> ContractReplayRow:
    raw_draft = raw.get("draft") if isinstance(raw, dict) else None
    if not section_copy_blocks_include_winner_claim(raw_draft):
        return ContractReplayRow(
            case_id=case.case_id,
            classification="parser_invalid",
        )
    try:
        draft = CopywriterDraft.model_validate(raw_draft, strict=True)
    except (TypeError, ValidationError, ValueError):
        return ContractReplayRow(
            case_id=case.case_id,
            classification="parser_invalid",
        )
    try:
        validate_copywriter_draft(case.packet, draft)
    except CopywriterValidationError as error:
        return ContractReplayRow(
            case_id=case.case_id,
            classification="validation_failure",
            validation_error_code=error.code.value,
        )
    compiled = _compile(case, draft)
    return ContractReplayRow(
        case_id=case.case_id,
        classification="section_contract",
        compiler_copy_source=compiled.copy_source,
        compiler_fallback_reason=compiled.telemetry.fallback_reason,
    )


def _compile(
    case: PresentationCopyGateCase,
    draft: CopywriterDraft,
):
    packet = case.packet
    product_ids = tuple(slot.product_id for slot in packet.slots)
    card_display = (
        CardDisplayContract(
            mode="none",
            visible_product_ids=(),
            max_cards=0,
            reason=None,
        )
        if not product_ids
        else CardDisplayContract(
            mode="single" if len(product_ids) == 1 else "comparison",
            visible_product_ids=product_ids,
            max_cards=len(product_ids),
            reason="product" if len(product_ids) == 1 else "comparison",
        )
    )
    return compile_presentation(
        PresentationCompileInputs(
            packet=packet,
            card_display=card_display,
            public_mode=decision_for_responsibility(
                packet.responsibility
            ).presentation_mode,
        ),
        copywriter=_ReplayCopywriter(draft),
    )


def _cases_sha256(
    cases: Sequence[PresentationCopyGateCase],
) -> str:
    return sha256(
        b"".join(
            json.dumps(
                case.model_dump(mode="json"),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            + b"\n"
            for case in cases
        )
    ).hexdigest()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", required=True)
    parser.add_argument("--results", required=True)
    parser.add_argument("--output", required=True)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    report = replay_copywriter_contract_results(
        cases=load_copy_gate_cases(args.cases),
        results_path=args.results,
        output_path=args.output,
    )
    print(report.model_dump_json())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "ContractReplayReport",
    "ContractReplayRow",
    "replay_copywriter_contract_results",
]
