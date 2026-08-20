from __future__ import annotations

from collections.abc import Mapping, Sequence
import json
from pathlib import Path
from typing import Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from app.guide.presentation.copywriter_contracts import (
    ApprovedSoftFact,
    CategoryProfileValue,
    CopyLengthBudget,
    CopySlot,
    CopywriterDraft,
    CopywriterSection,
    DimensionId,
    DirectCaution,
    FactAttribution,
    LockedFact,
    PresentationMode,
    PresentationPacket,
    PresentationSectionSpec,
    build_copywriter_section_specs,
    responsibility_for_presentation_mode,
    section_copy_blocks_include_winner_claim,
)
from app.guide.presentation.copywriter_validation import (
    CopywriterValidationError,
    CopywriterValidationErrorCode,
    validate_copywriter_draft,
)


WinnerLanguagePolicy = Literal["allowed", "forbidden"]
RequiredAttributionKind = Literal[
    "merchant_claim",
    "consumer_report",
]
_INTERNAL_LANGUAGE = (
    "候选",
    "同档排序",
    "预算利用度",
    "预算利用算法",
    "约束优先级",
    "内部候选集",
    "代码核对",
    "硬条件",
    "证据等级",
    "放行",
    "页面记录版本",
    "本轮筛选",
    "已核验记录",
    "已核验商品记录",
    "现有目录",
    "原字段边界",
)


class _StrictFrozenModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
        protected_namespaces=(),
    )


def _tuple(value: object) -> object:
    return tuple(value) if isinstance(value, list) else value


def _require_unique(values: Sequence[str], *, label: str) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"{label} must be unique")


class GateSoftFact(_StrictFrozenModel):
    fact_id: str = Field(min_length=1, max_length=160)
    field_key: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    dimension_ids: tuple[DimensionId, ...] = ()
    plain_meaning: str = Field(min_length=1, max_length=512)
    attribution: FactAttribution

    @field_validator("dimension_ids", mode="before")
    @classmethod
    def freeze_dimension_ids(cls, value: object) -> object:
        return _tuple(value)

    @model_validator(mode="after")
    def validate_dimensions(self) -> Self:
        dimension_ids = (
            self.dimension_ids
            if self.dimension_ids
            else (self.field_key,)
        )
        if any(
            dimension_id != self.field_key
            and not dimension_id.startswith(f"{self.field_key}.")
            for dimension_id in dimension_ids
        ):
            raise ValueError(
                "gate soft fact dimensions must belong to its field"
            )
        _require_unique(
            dimension_ids,
            label="gate soft fact dimension IDs",
        )
        object.__setattr__(self, "dimension_ids", dimension_ids)
        return self


class GateLockedFact(_StrictFrozenModel):
    fact_id: str = Field(min_length=1, max_length=160)
    kind: Literal[
        "price",
        "specification",
        "numeric",
        "ingredient",
        "package_warning",
        "merchant_quote",
        "consumer_quote",
        "verified_text",
    ]
    label: str = Field(min_length=1, max_length=64)
    display_value: str = Field(min_length=1, max_length=512)


class GateSlot(_StrictFrozenModel):
    slot_id: str = Field(pattern=r"^p[1-4]$")
    product_id: int = Field(gt=0)
    name: str = Field(min_length=1, max_length=256)
    category_profile: CategoryProfileValue
    soft_facts: tuple[GateSoftFact, ...] = Field(
        default_factory=tuple,
        max_length=8,
    )
    locked_facts: tuple[GateLockedFact, ...] = Field(
        default_factory=tuple,
        max_length=12,
    )
    cautions: tuple[str, ...] = Field(
        default_factory=tuple,
        max_length=6,
    )

    @field_validator(
        "soft_facts",
        "locked_facts",
        "cautions",
        mode="before",
    )
    @classmethod
    def freeze_collections(cls, value: object) -> object:
        return _tuple(value)

    @model_validator(mode="after")
    def validate_ids(self) -> Self:
        _require_unique(
            tuple(fact.fact_id for fact in self.soft_facts),
            label="gate soft fact IDs",
        )
        _require_unique(
            tuple(fact.fact_id for fact in self.locked_facts),
            label="gate locked fact IDs",
        )
        return self

    def to_copy_slot(self) -> CopySlot:
        return CopySlot(
            slot_id=self.slot_id,
            product_id=self.product_id,
            name=self.name,
            category_profile=self.category_profile,
            approved_soft_facts=tuple(
                ApprovedSoftFact(
                    fact_id=fact.fact_id,
                    product_id=self.product_id,
                    field_key=fact.field_key,
                    dimension_ids=fact.dimension_ids,
                    plain_meaning=fact.plain_meaning,
                    attribution=fact.attribution,
                    source_refs=(
                        f"gate:{self.slot_id}:{fact.fact_id}",
                    ),
                )
                for fact in self.soft_facts
            ),
            locked_facts=tuple(
                LockedFact(
                    fact_id=fact.fact_id,
                    product_id=self.product_id,
                    kind=fact.kind,
                    label=fact.label,
                    display_value=fact.display_value,
                    source_refs=(
                        f"gate:{self.slot_id}:{fact.fact_id}",
                    ),
                )
                for fact in self.locked_facts
            ),
            required_cautions=tuple(
                DirectCaution(
                    caution_id=f"caution-{self.slot_id}-{index}",
                    product_id=self.product_id,
                    severity="high" if index == 1 else "medium",
                    text=text,
                    source_refs=(
                        f"gate:{self.slot_id}:caution:{index}",
                    ),
                )
                for index, text in enumerate(self.cautions, start=1)
            ),
        )


class RequiredAttribution(_StrictFrozenModel):
    slot_id: str = Field(pattern=r"^p[1-4]$")
    fact_id: str = Field(min_length=1, max_length=160)
    attribution: RequiredAttributionKind
    accepted_markers: tuple[str, ...] = Field(min_length=1)

    @field_validator("accepted_markers", mode="before")
    @classmethod
    def freeze_markers(cls, value: object) -> object:
        return _tuple(value)


class CopyReadabilityRubric(_StrictFrozenModel):
    summary_min_chars: int = Field(ge=1, le=120)
    product_field_min_chars: int = Field(ge=1, le=80)
    closing_min_chars: int = Field(ge=0, le=120)
    require_closing: bool
    require_soft_fact_use: bool


class PresentationCopyGateCase(_StrictFrozenModel):
    schema_version: Literal[
        "guide-presentation-copy-gate-v1"
    ] = "guide-presentation-copy-gate-v1"
    case_id: str = Field(min_length=1, max_length=128)
    mode: PresentationMode
    user_need_summary: str = Field(min_length=1, max_length=512)
    winner_status: str | None = Field(default=None, max_length=96)
    slots: tuple[GateSlot, ...] = Field(default_factory=tuple, max_length=4)
    required_slots: tuple[str, ...]
    allowed_soft_fact_ids: dict[str, tuple[str, ...]]
    required_dimensions: tuple[str, ...] = ()
    locked_atoms: tuple[str, ...]
    winner_language_policy: WinnerLanguagePolicy
    required_attribution: tuple[RequiredAttribution, ...] = ()
    forbidden_factual_claims: tuple[str, ...] = ()
    readability: CopyReadabilityRubric
    dont_care_wording: tuple[str, ...] = Field(min_length=1)

    @field_validator(
        "slots",
        "required_slots",
        "required_dimensions",
        "locked_atoms",
        "required_attribution",
        "forbidden_factual_claims",
        "dont_care_wording",
        mode="before",
    )
    @classmethod
    def freeze_collections(cls, value: object) -> object:
        return _tuple(value)

    @field_validator("allowed_soft_fact_ids", mode="before")
    @classmethod
    def freeze_allowed_fact_ids(cls, value: object) -> object:
        if not isinstance(value, Mapping):
            return value
        return {
            str(slot_id): _tuple(fact_ids)
            for slot_id, fact_ids in value.items()
        }

    @model_validator(mode="after")
    def validate_fixture_truth(self) -> Self:
        _require_unique(
            self.required_dimensions,
            label="required dimensions",
        )
        slot_ids = tuple(slot.slot_id for slot in self.slots)
        if slot_ids != self.required_slots:
            raise ValueError("required slots must match fixture slot order")
        _require_unique(slot_ids, label="gate slot IDs")
        if set(self.allowed_soft_fact_ids) != set(slot_ids):
            raise ValueError(
                "allowed soft fact map must exactly match fixture slots"
            )
        for slot in self.slots:
            expected = tuple(fact.fact_id for fact in slot.soft_facts)
            actual = self.allowed_soft_fact_ids[slot.slot_id]
            if actual != expected:
                raise ValueError(
                    "allowed soft fact IDs must match fixture facts"
                )
            _require_unique(
                actual,
                label="allowed soft fact IDs",
            )
        expected_atoms = tuple(
            atom
            for slot in self.slots
            for atom in (
                *(
                    fact.display_value
                    for fact in slot.locked_facts
                ),
                *slot.cautions,
            )
        )
        if self.locked_atoms != expected_atoms:
            raise ValueError(
                "locked atoms must match fixture facts and cautions"
            )
        expected_attribution = {
            (slot.slot_id, fact.fact_id, fact.attribution)
            for slot in self.slots
            for fact in slot.soft_facts
            if fact.attribution in {
                "merchant_claim",
                "consumer_report",
            }
        }
        actual_attribution = {
            (
                item.slot_id,
                item.fact_id,
                item.attribution,
            )
            for item in self.required_attribution
        }
        if actual_attribution != expected_attribution:
            raise ValueError(
                "required attribution must match attributed soft facts"
            )
        _require_unique(self.locked_atoms, label="locked atoms")
        _require_unique(
            self.forbidden_factual_claims,
            label="forbidden factual claims",
        )
        winner_allowed = self.winner_status in {"SELECTED", "WINNER"}
        if (self.winner_language_policy == "allowed") != winner_allowed:
            raise ValueError(
                "winner policy must match packet winner status"
            )
        return self

    @property
    def packet(self) -> PresentationPacket:
        copy_slots = tuple(slot.to_copy_slot() for slot in self.slots)
        return PresentationPacket(
            mode=self.mode,
            user_need_summary=self.user_need_summary,
            winner_status=self.winner_status,
            slots=copy_slots,
            section_order=_section_order(
                mode=self.mode,
                slot_ids=self.required_slots,
            ),
            requested_dimensions=self.required_dimensions,
            copy_budget=CopyLengthBudget(
                summary_max_chars=180,
                positioning_max_chars=90,
                advisor_reason_max_chars=100,
                closing_max_chars=180,
            ),
        )


class PresentationCopyGateRow(_StrictFrozenModel):
    case_id: str
    provider_call_count: int = Field(ge=0)
    schema_valid: bool
    slot_binding_passed: bool
    fact_grounding_passed: bool
    hard_atoms_passed: bool
    winner_language_passed: bool
    attribution_passed: bool
    fact_coverage_passed: bool
    minimum_fact_coverage: float = Field(ge=0.0, le=1.0)
    internal_language_passed: bool
    readability_passed: bool
    provider_call_violation_count: int = Field(ge=0)
    slot_binding_violation_count: int = Field(ge=0)
    fact_grounding_violation_count: int = Field(ge=0)
    hard_atom_violation_count: int = Field(ge=0)
    winner_language_violation_count: int = Field(ge=0)
    attribution_violation_count: int = Field(ge=0)
    fact_coverage_violation_count: int = Field(ge=0)
    internal_language_violation_count: int = Field(ge=0)
    validation_error_code: str | None
    passed: bool

    @property
    def hard_violation_count(self) -> int:
        return sum(
            (
                self.provider_call_violation_count,
                self.slot_binding_violation_count,
                self.fact_grounding_violation_count,
                self.hard_atom_violation_count,
                self.winner_language_violation_count,
                self.attribution_violation_count,
                self.internal_language_violation_count,
            )
        )


class PresentationCopyGateSummary(_StrictFrozenModel):
    case_count: int = Field(ge=0)
    passed_count: int = Field(ge=0)
    schema_valid_count: int = Field(ge=0)
    readability_passed_count: int = Field(ge=0)
    fact_coverage_passed_count: int = Field(ge=0)
    internal_language_passed_count: int = Field(ge=0)
    schema_valid_rate: float = Field(ge=0.0, le=1.0)
    readability_rate: float = Field(ge=0.0, le=1.0)
    fact_coverage_rate: float = Field(ge=0.0, le=1.0)
    minimum_fact_coverage: float = Field(ge=0.0, le=1.0)
    internal_language_rate: float = Field(ge=0.0, le=1.0)
    provider_call_violation_count: int = Field(ge=0)
    slot_binding_violation_count: int = Field(ge=0)
    fact_grounding_violation_count: int = Field(ge=0)
    hard_atom_violation_count: int = Field(ge=0)
    winner_language_violation_count: int = Field(ge=0)
    attribution_violation_count: int = Field(ge=0)
    fact_coverage_violation_count: int = Field(ge=0)
    internal_language_violation_count: int = Field(ge=0)
    hard_violation_count: int = Field(ge=0)
    passed: bool


def load_copy_gate_cases(
    path: str | Path,
) -> tuple[PresentationCopyGateCase, ...]:
    rows = tuple(
        PresentationCopyGateCase.model_validate_json(line, strict=True)
        for line in Path(path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    )
    case_ids = tuple(row.case_id for row in rows)
    _require_unique(case_ids, label="copy gate case IDs")
    if case_ids != tuple(sorted(case_ids)):
        raise ValueError("copy gate cases must be sorted by case ID")
    return rows


def evaluate_copy_gate_output(
    *,
    case: PresentationCopyGateCase,
    output: object,
    provider_call_count: int,
) -> PresentationCopyGateRow:
    if not isinstance(case, PresentationCopyGateCase):
        raise TypeError("case must be PresentationCopyGateCase")
    if (
        not isinstance(provider_call_count, int)
        or isinstance(provider_call_count, bool)
        or provider_call_count < 0
    ):
        raise ValueError("provider_call_count must be a nonnegative integer")
    call_violation = int(provider_call_count != 1)
    try:
        draft = _parse_draft(output)
    except (TypeError, ValidationError, ValueError):
        return PresentationCopyGateRow(
            case_id=case.case_id,
            provider_call_count=provider_call_count,
            schema_valid=False,
            slot_binding_passed=False,
            fact_grounding_passed=False,
            hard_atoms_passed=False,
            winner_language_passed=False,
            attribution_passed=False,
            fact_coverage_passed=False,
            minimum_fact_coverage=0.0,
            internal_language_passed=False,
            readability_passed=False,
            provider_call_violation_count=call_violation,
            slot_binding_violation_count=0,
            fact_grounding_violation_count=0,
            hard_atom_violation_count=0,
            winner_language_violation_count=0,
            attribution_violation_count=0,
            fact_coverage_violation_count=0,
            internal_language_violation_count=0,
            validation_error_code="schema_invalid",
            passed=False,
        )

    violations = {
        "slot": 0,
        "fact": 0,
        "hard": 0,
        "winner": 0,
        "attribution": 0,
        "coverage": 0,
        "internal": 0,
    }
    validation_code: str | None = None
    try:
        validate_copywriter_draft(case.packet, draft)
    except CopywriterValidationError as error:
        validation_code = error.code.value
        _record_validation_violation(violations, error.code)

    rendered = _rendered_copy(draft)
    if any(
        _contains_atom(rendered, atom)
        for atom in case.locked_atoms
    ):
        violations["hard"] = 1
    if any(
        _contains_atom(rendered, claim)
        for claim in case.forbidden_factual_claims
    ):
        violations["fact"] = 1
    if not _fact_ids_match_fixture(case, draft):
        violations["fact"] = 1
    if not _attribution_matches_fixture(case, draft):
        violations["attribution"] = 1
    minimum_fact_coverage = _minimum_fact_coverage(case, draft)
    if minimum_fact_coverage < 0.8:
        violations["coverage"] = 1
    internal_language_passed = not _contains_internal_language(
        rendered
    )
    if not internal_language_passed:
        violations["internal"] = 1

    readability_passed = (
        validation_code
        not in {
            CopywriterValidationErrorCode.LENGTH.value,
            CopywriterValidationErrorCode.MARKUP.value,
        }
        and _passes_readability(case, draft)
    )
    hard_total = call_violation + sum(
        count
        for name, count in violations.items()
        if name != "coverage"
    )
    return PresentationCopyGateRow(
        case_id=case.case_id,
        provider_call_count=provider_call_count,
        schema_valid=True,
        slot_binding_passed=violations["slot"] == 0,
        fact_grounding_passed=violations["fact"] == 0,
        hard_atoms_passed=violations["hard"] == 0,
        winner_language_passed=violations["winner"] == 0,
        attribution_passed=violations["attribution"] == 0,
        fact_coverage_passed=violations["coverage"] == 0,
        minimum_fact_coverage=minimum_fact_coverage,
        internal_language_passed=internal_language_passed,
        readability_passed=readability_passed,
        provider_call_violation_count=call_violation,
        slot_binding_violation_count=violations["slot"],
        fact_grounding_violation_count=violations["fact"],
        hard_atom_violation_count=violations["hard"],
        winner_language_violation_count=violations["winner"],
        attribution_violation_count=violations["attribution"],
        fact_coverage_violation_count=violations["coverage"],
        internal_language_violation_count=violations["internal"],
        validation_error_code=validation_code,
        passed=(
            validation_code is None
            and hard_total == 0
            and violations["coverage"] == 0
            and readability_passed
        ),
    )


def summarize_copy_gate(
    rows: Sequence[PresentationCopyGateRow],
) -> PresentationCopyGateSummary:
    normalized = tuple(rows)
    if any(
        not isinstance(row, PresentationCopyGateRow)
        for row in normalized
    ):
        raise TypeError("rows must contain PresentationCopyGateRow values")
    case_ids = tuple(row.case_id for row in normalized)
    _require_unique(case_ids, label="copy gate summary case IDs")
    case_count = len(normalized)
    schema_valid_count = sum(row.schema_valid for row in normalized)
    readability_passed_count = sum(
        row.readability_passed for row in normalized
    )
    fact_coverage_passed_count = sum(
        row.fact_coverage_passed for row in normalized
    )
    internal_language_passed_count = sum(
        row.internal_language_passed for row in normalized
    )
    counts = {
        "provider": sum(
            row.provider_call_violation_count for row in normalized
        ),
        "slot": sum(
            row.slot_binding_violation_count for row in normalized
        ),
        "fact": sum(
            row.fact_grounding_violation_count for row in normalized
        ),
        "hard": sum(
            row.hard_atom_violation_count for row in normalized
        ),
        "winner": sum(
            row.winner_language_violation_count for row in normalized
        ),
        "attribution": sum(
            row.attribution_violation_count for row in normalized
        ),
        "coverage": sum(
            row.fact_coverage_violation_count for row in normalized
        ),
        "internal": sum(
            row.internal_language_violation_count for row in normalized
        ),
    }
    hard_violation_count = sum(
        count
        for name, count in counts.items()
        if name != "coverage"
    )
    schema_rate = (
        schema_valid_count / case_count if case_count else 0.0
    )
    readability_rate = (
        readability_passed_count / case_count
        if case_count
        else 0.0
    )
    fact_coverage_rate = (
        fact_coverage_passed_count / case_count
        if case_count
        else 0.0
    )
    internal_language_rate = (
        internal_language_passed_count / case_count
        if case_count
        else 0.0
    )
    minimum_fact_coverage = min(
        (row.minimum_fact_coverage for row in normalized),
        default=0.0,
    )
    minimum_qualified_count = (
        (case_count * 9 + 9) // 10
        if case_count
        else 0
    )
    passed_count = sum(row.passed for row in normalized)
    return PresentationCopyGateSummary(
        case_count=case_count,
        passed_count=passed_count,
        schema_valid_count=schema_valid_count,
        readability_passed_count=readability_passed_count,
        fact_coverage_passed_count=fact_coverage_passed_count,
        internal_language_passed_count=(
            internal_language_passed_count
        ),
        schema_valid_rate=schema_rate,
        readability_rate=readability_rate,
        fact_coverage_rate=fact_coverage_rate,
        minimum_fact_coverage=minimum_fact_coverage,
        internal_language_rate=internal_language_rate,
        provider_call_violation_count=counts["provider"],
        slot_binding_violation_count=counts["slot"],
        fact_grounding_violation_count=counts["fact"],
        hard_atom_violation_count=counts["hard"],
        winner_language_violation_count=counts["winner"],
        attribution_violation_count=counts["attribution"],
        fact_coverage_violation_count=counts["coverage"],
        internal_language_violation_count=counts["internal"],
        hard_violation_count=hard_violation_count,
        passed=(
            case_count > 0
            and passed_count >= minimum_qualified_count
            and schema_valid_count >= minimum_qualified_count
            and readability_passed_count >= minimum_qualified_count
            and fact_coverage_passed_count >= minimum_qualified_count
            and internal_language_rate == 1.0
            and hard_violation_count == 0
        ),
    )


def _section_order(
    *,
    mode: PresentationMode,
    slot_ids: tuple[str, ...],
) -> tuple[PresentationSectionSpec, ...]:
    responsibility = responsibility_for_presentation_mode(mode)
    if mode == "clarification":
        return (PresentationSectionSpec(kind="question"),)
    if mode == "error":
        return (PresentationSectionSpec(kind="error"),)
    if responsibility.value == "consultation":
        return (
            PresentationSectionSpec(kind="observation"),
            PresentationSectionSpec(kind="summary"),
        )
    if responsibility.value == "general_knowledge":
        return (
            PresentationSectionSpec(kind="general_knowledge"),
        )
    if responsibility.value == "image_identity":
        return (
            PresentationSectionSpec(kind="observation"),
            PresentationSectionSpec(kind="full_cards"),
        )
    if not slot_ids:
        return (
            PresentationSectionSpec(kind="summary"),
            PresentationSectionSpec(kind="closing"),
        )
    if responsibility.value == "product_knowledge":
        return (
            PresentationSectionSpec(kind="summary"),
            PresentationSectionSpec(kind="answer"),
            PresentationSectionSpec(kind="full_cards"),
        )
    if responsibility.value == "single_product_suitability":
        return (
            PresentationSectionSpec(kind="summary"),
            PresentationSectionSpec(kind="judgement"),
            PresentationSectionSpec(kind="full_cards"),
        )
    if responsibility.value == "comparison":
        return (
            PresentationSectionSpec(kind="summary"),
            PresentationSectionSpec(kind="comparison"),
            PresentationSectionSpec(kind="full_cards"),
        )
    return (
        PresentationSectionSpec(kind="summary"),
        *(
            PresentationSectionSpec(
                kind="product",
                slot_id=slot_id,
            )
            for slot_id in slot_ids
        ),
        PresentationSectionSpec(kind="closing"),
        PresentationSectionSpec(kind="full_cards"),
    )


def _parse_draft(output: object) -> CopywriterDraft:
    if isinstance(output, CopywriterDraft):
        return output
    if isinstance(output, (str, bytes, bytearray)):
        raw = json.loads(output)
        if not section_copy_blocks_include_winner_claim(raw):
            raise ValueError(
                "section copy is missing structured winner claim"
            )
        return CopywriterDraft.model_validate_json(output, strict=True)
    if not section_copy_blocks_include_winner_claim(output):
        raise ValueError(
            "section copy is missing structured winner claim"
        )
    return CopywriterDraft.model_validate_json(
        json.dumps(
            output,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
        strict=True,
    )


def _record_validation_violation(
    violations: dict[str, int],
    code: CopywriterValidationErrorCode,
) -> None:
    if code in {
        CopywriterValidationErrorCode.MODE_MISMATCH,
        CopywriterValidationErrorCode.SLOT_MISMATCH,
    }:
        violations["slot"] = 1
    elif code in {
        CopywriterValidationErrorCode.FACT_ID_MISMATCH,
        CopywriterValidationErrorCode.PRODUCT_NAME,
        CopywriterValidationErrorCode.CATEGORY_MISMATCH,
    }:
        violations["fact"] = 1
    elif code is CopywriterValidationErrorCode.FACT_COVERAGE:
        violations["coverage"] = 1
    elif code in {
        CopywriterValidationErrorCode.HARD_FACT,
        CopywriterValidationErrorCode.INGREDIENT,
        CopywriterValidationErrorCode.MARKUP,
    }:
        violations["hard"] = 1
    elif code is CopywriterValidationErrorCode.WINNER_LANGUAGE:
        violations["winner"] = 1
    elif code in {
        CopywriterValidationErrorCode.SAFETY_GUARANTEE,
        CopywriterValidationErrorCode.ATTRIBUTION,
    }:
        violations["attribution"] = 1
    elif code is CopywriterValidationErrorCode.INTERNAL_LANGUAGE:
        violations["internal"] = 1


def _rendered_copy(draft: CopywriterDraft) -> str:
    if draft.summary_copy is None:
        return " ".join(
            text
            for section in draft.sections
            for text in (
                section.content.text,
                (
                    section.advisor_reason.text
                    if section.advisor_reason is not None
                    else ""
                ),
            )
            if text
        )
    return " ".join(
        (
            draft.summary_copy.text,
            *(
                text
                for item in draft.product_copy
                for text in (
                    item.positioning.text,
                    item.advisor_reason.text,
                )
            ),
            (
                draft.closing_copy.text
                if draft.closing_copy is not None
                else ""
            ),
        )
    )


def _contains_atom(text: str, atom: str) -> bool:
    return atom.strip().casefold() in text.casefold()


def _fact_ids_match_fixture(
    case: PresentationCopyGateCase,
    draft: CopywriterDraft,
) -> bool:
    if draft.summary_copy is None:
        specs = build_copywriter_section_specs(case.packet)
        section_by_key = {
            (section.kind, section.slot_id): section
            for section in draft.sections
        }
        if set(section_by_key) != {
            (spec.kind, spec.slot_id) for spec in specs
        }:
            return False
        for spec in specs:
            section = section_by_key[(spec.kind, spec.slot_id)]
            allowed = set(spec.allowed_fact_ids)
            used = {
                *section.content.used_fact_ids,
                *(
                    section.advisor_reason.used_fact_ids
                    if section.advisor_reason is not None
                    else ()
                ),
            }
            if not used.issubset(allowed):
                return False
        return True
    if tuple(item.slot_id for item in draft.product_copy) != (
        case.required_slots
    ):
        return False
    return all(
        _used_fact_ids(item).issubset(
            case.allowed_soft_fact_ids[item.slot_id]
        )
        for item in draft.product_copy
    )


def _minimum_fact_coverage(
    case: PresentationCopyGateCase,
    draft: CopywriterDraft,
) -> float:
    if draft.summary_copy is None:
        if not case.required_dimensions:
            return 1.0
        specs = build_copywriter_section_specs(case.packet)
        facts_by_id = {
            fact.fact_id: fact
            for slot in case.slots
            for fact in slot.soft_facts
        }
        used = {
            fact_id
            for section in draft.sections
            for fact_id in (
                *section.content.used_fact_ids,
                *(
                    section.advisor_reason.used_fact_ids
                    if section.advisor_reason is not None
                    else ()
                ),
            )
        }
        covered_dimensions = {
            dimension_id
            for dimension_id in case.required_dimensions
            if any(
                _fact_covers_dimension(
                    facts_by_id[fact_id],
                    dimension_id,
                )
                for fact_id in used
                if fact_id in facts_by_id
            )
        }
        model_owned_required_dimensions = {
            dimension_id
            for dimension_id in case.required_dimensions
            if any(
                _fact_covers_dimension(
                    facts_by_id[fact_id],
                    dimension_id,
                )
                for spec in specs
                if spec.content_source == "approved_facts"
                for fact_id in spec.allowed_fact_ids
                if fact_id in facts_by_id
            )
        }
        return (
            (
                len(
                    model_owned_required_dimensions
                    & covered_dimensions
                )
                / len(model_owned_required_dimensions)
            )
            if model_owned_required_dimensions
            else 1.0
        )
    copy_by_slot = {
        item.slot_id: item for item in draft.product_copy
    }
    coverage = []
    for slot in case.slots:
        allowed = set(case.allowed_soft_fact_ids[slot.slot_id])
        if not allowed:
            continue
        item = copy_by_slot.get(slot.slot_id)
        used = (
            _used_fact_ids(item)
            if item is not None
            else set()
        )
        coverage.append(len(used & allowed) / len(allowed))
    return min(coverage, default=1.0)


def _fact_covers_dimension(
    fact: GateSoftFact,
    dimension_id: str,
) -> bool:
    if "." not in dimension_id:
        return fact.field_key == dimension_id
    return dimension_id in fact.dimension_ids


def _contains_internal_language(text: str) -> bool:
    lowered = text.casefold()
    return any(term.casefold() in lowered for term in _INTERNAL_LANGUAGE)


def _attribution_matches_fixture(
    case: PresentationCopyGateCase,
    draft: CopywriterDraft,
) -> bool:
    if draft.summary_copy is None:
        sections_by_slot: dict[str, list[CopywriterSection]] = {}
        for section in draft.sections:
            if section.slot_id is not None:
                sections_by_slot.setdefault(section.slot_id, []).append(
                    section
                )
        for requirement in case.required_attribution:
            sections = sections_by_slot.get(requirement.slot_id, ())
            used = {
                fact_id
                for section in sections
                for fact_id in (
                    *section.content.used_fact_ids,
                    *(
                        section.advisor_reason.used_fact_ids
                        if section.advisor_reason is not None
                        else ()
                    ),
                )
            }
            if requirement.fact_id not in used:
                continue
            text = " ".join(
                value
                for section in sections
                for value in (
                    section.content.text,
                    (
                        section.advisor_reason.text
                        if section.advisor_reason is not None
                        else None
                    ),
                )
                if value is not None
            )
            if not any(marker in text for marker in requirement.accepted_markers):
                return False
        return True
    copy_by_slot = {
        item.slot_id: item for item in draft.product_copy
    }
    for requirement in case.required_attribution:
        item = copy_by_slot.get(requirement.slot_id)
        if item is None:
            return False
        if requirement.fact_id not in _used_fact_ids(item):
            continue
        text = f"{item.positioning.text} {item.advisor_reason.text}"
        if not any(
            marker in text
            for marker in requirement.accepted_markers
        ):
            return False
    return True


def _passes_readability(
    case: PresentationCopyGateCase,
    draft: CopywriterDraft,
) -> bool:
    rubric = case.readability
    if draft.summary_copy is None:
        specs = build_copywriter_section_specs(case.packet)
        sections = {
            (section.kind, section.slot_id): section
            for section in draft.sections
        }
        summary = next(
            (
                sections[(spec.kind, spec.slot_id)]
                for spec in specs
                if spec.kind in {"summary", "general_knowledge"}
            ),
            None,
        )
        if summary is not None and (
            len(summary.content.text.strip()) < rubric.summary_min_chars
        ):
            return False
        closing = sections.get(("closing", None))
        if rubric.require_closing:
            if closing is None or (
                len(closing.content.text.strip()) < rubric.closing_min_chars
            ):
                return False
        for spec in specs:
            if spec.kind != "product":
                continue
            section = sections[(spec.kind, spec.slot_id)]
            if section.advisor_reason is None:
                return False
            if (
                len(section.content.text.strip())
                + len(section.advisor_reason.text.strip())
                < rubric.product_field_min_chars * 2
            ):
                return False
        if (
            rubric.require_soft_fact_use
            and case.required_dimensions
            and _minimum_fact_coverage(case, draft) < 1.0
        ):
            return False
        return not any(
            term in _rendered_copy(draft).casefold()
            for term in (
                "数据库",
                "系统提示",
                "语言模型",
                "候选 id",
                "slot_id",
            )
        )
    if len(draft.summary_copy.text.strip()) < rubric.summary_min_chars:
        return False
    if rubric.require_closing:
        if draft.closing_copy is None:
            return False
        if (
            len(draft.closing_copy.text.strip())
            < rubric.closing_min_chars
        ):
            return False
    for item in draft.product_copy:
        positioning_length = len(item.positioning.text.strip())
        reason_length = len(item.advisor_reason.text.strip())
        if reason_length < rubric.product_field_min_chars:
            return False
        if positioning_length < rubric.product_field_min_chars:
            concise_floor = min(5, rubric.product_field_min_chars)
            if (
                positioning_length < concise_floor
                or positioning_length + reason_length
                < rubric.product_field_min_chars * 2
            ):
                return False
    if (
        rubric.require_soft_fact_use
        and any(
            slot.soft_facts and not _used_fact_ids(item)
            for slot, item in zip(
                case.slots,
                draft.product_copy,
                strict=True,
            )
        )
    ):
        return False
    lowered = _rendered_copy(draft).casefold()
    return not any(
        term in lowered
        for term in (
            "数据库",
            "系统提示",
            "语言模型",
            "候选 id",
            "slot_id",
        )
    )


def _used_fact_ids(item) -> set[str]:
    return {
        *item.positioning.used_fact_ids,
        *item.advisor_reason.used_fact_ids,
    }


__all__ = [
    "CopyReadabilityRubric",
    "GateLockedFact",
    "GateSlot",
    "GateSoftFact",
    "PresentationCopyGateCase",
    "PresentationCopyGateRow",
    "PresentationCopyGateSummary",
    "RequiredAttribution",
    "evaluate_copy_gate_output",
    "load_copy_gate_cases",
    "summarize_copy_gate",
]
