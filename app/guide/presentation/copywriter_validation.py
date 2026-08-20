from __future__ import annotations

from enum import Enum
import re

from app.guide.intent.responsibility_matrix import Responsibility
from app.guide.presentation.copy_evidence_validation import (
    CopyEvidenceError,
    validate_copy_evidence,
    validate_copywriter_evidence,
)
from app.guide.presentation.copywriter_contracts import (
    CopywriterDraft,
    CopywriterSection,
    CopywriterSectionSpec,
    PresentationPacket,
    SourceTaggedCopy,
    build_copywriter_section_specs,
)
from app.guide.presentation.public_language_policy import (
    PublicLanguageError,
    validate_final_public_text,
)


class CopywriterValidationErrorCode(str, Enum):
    MODE_MISMATCH = "mode_mismatch"
    SLOT_MISMATCH = "slot_mismatch"
    FACT_ID_MISMATCH = "fact_id_mismatch"
    FACT_COVERAGE = "fact_coverage"
    HARD_FACT = "hard_fact"
    INGREDIENT = "ingredient"
    PRODUCT_NAME = "product_name"
    CATEGORY_MISMATCH = "category_mismatch"
    WINNER_LANGUAGE = "winner_language"
    SAFETY_GUARANTEE = "safety_guarantee"
    MARKUP = "markup"
    ATTRIBUTION = "attribution"
    INTERNAL_LANGUAGE = "internal_language"
    LENGTH = "length"
    REQUIRED_COPY = "required_copy"


class CopywriterValidationError(ValueError):
    def __init__(self, code: CopywriterValidationErrorCode) -> None:
        self.code = code
        super().__init__(f"Presentation copy rejected: {code.value}")


ValidatedCopywriterDraft = CopywriterDraft


_PRODUCT_INTRODUCTION = re.compile(
    r"(?:换成|改买|购买|入手|选择|推荐|看看)"
    r"[^，。！？\n]{1,24}"
    r"(?:防晒(?:乳|霜|液|喷雾)?|精华(?:液)?|面霜|洁面(?:乳)?|"
    r"口红|粉底(?:液)?|香水)"
)
_CATEGORY_TERMS = {
    "skincare": re.compile(r"精华(?:液|露)?|面霜|护肤乳液"),
    "suncare": re.compile(r"防晒(?:乳|霜|液|喷雾)?"),
    "base_makeup": re.compile(r"底妆|粉底(?:液)?|气垫"),
    "cleanser": re.compile(r"洁面(?:乳)?|洗面奶"),
    "color_makeup": re.compile(r"口红|唇釉|腮红|眼影"),
    "fragrance": re.compile(r"香水|香氛"),
}
_SAFETY_GUARANTEE = re.compile(
    r"保证不过敏|绝不过敏|不会过敏|不闷痘|零风险|绝对安全|"
    r"百分百安全|包治|治愈|治疗(?:痤疮|皮炎|湿疹|过敏)"
)
_MARKUP = re.compile(
    r"<\s*/?\s*[a-zA-Z][^>]*>|"
    r"(?:^|\n)\s{0,3}#{1,6}\s|"
    r"(?:^|\n)\s*[-+*]\s+|"
    r"\[[^\]]+\]\([^)]*\)|"
    r"!\[[^\]]*\]\([^)]*\)|"
    r"\*\*|__|~~|```|`[^`]+`"
)
_MERCHANT_ATTRIBUTION = re.compile(
    r"商家|主打|品牌(?:资料|页面|介绍|主打|宣称)|"
    r"官方(?:资料|页面|介绍)"
)
_CONSUMER_ATTRIBUTION = re.compile(
    r"用户反馈|使用者反馈|限定样本|样本反馈|评论反馈"
)
_INTERNAL_PUBLIC_LANGUAGE = re.compile(
    r"候选|代码核对|硬条件|证据等级|放行|页面记录版本|本轮筛选|"
    r"已核验(?:商品)?记录|现有目录|原字段边界|"
    r"品牌主打\s*[：:]\s*品牌主打"
)
_AUTHORIZED_WINNER_STATUSES = frozenset({"SELECTED", "WINNER"})
_PRODUCT_NAME_PLACEHOLDERS = frozenset({
    "无",
    "未知",
    "未命名",
    "n/a",
    "na",
    "-",
    "--",
})


def validate_copywriter_draft(
    packet: PresentationPacket,
    draft: CopywriterDraft,
) -> ValidatedCopywriterDraft:
    if not isinstance(packet, PresentationPacket):
        raise TypeError("packet must be PresentationPacket")
    if not isinstance(draft, CopywriterDraft):
        raise TypeError("draft must be CopywriterDraft")
    if draft.mode != packet.mode:
        _reject(CopywriterValidationErrorCode.MODE_MISMATCH)
    _validate_winner_claims(packet, draft)
    if draft.summary_copy is None:
        return _validate_section_draft(packet, draft)

    expected_slots = tuple(slot.slot_id for slot in packet.slots)
    actual_slots = tuple(item.slot_id for item in draft.product_copy)
    if actual_slots != expected_slots:
        _reject(CopywriterValidationErrorCode.SLOT_MISMATCH)

    slot_by_id = {slot.slot_id: slot for slot in packet.slots}
    try:
        validate_copywriter_evidence(packet, draft)
    except CopyEvidenceError:
        _reject(CopywriterValidationErrorCode.FACT_ID_MISMATCH)
    for item in draft.product_copy:
        slot = slot_by_id[item.slot_id]
        used_fact_ids = {
            *item.positioning.used_fact_ids,
            *item.advisor_reason.used_fact_ids,
        }
        generic_copy = packet.responsibility in {
            Responsibility.RECOMMENDATION,
            Responsibility.COMPARISON,
        }
        usable_facts = tuple(
            fact
            for fact in slot.approved_soft_facts
            if not generic_copy or fact.generic_copy_allowed
        )
        required_count = 1 if usable_facts else 0
        if len(used_fact_ids) < required_count:
            _reject(CopywriterValidationErrorCode.FACT_COVERAGE)
        _validate_product_attribution(slot, item)
    _validate_shared_attribution(packet, draft.summary_copy)
    if draft.closing_copy is not None:
        _validate_shared_attribution(packet, draft.closing_copy)

    if (
        any(
            section.kind == "closing"
            for section in packet.section_order
        )
        and draft.closing_copy is None
    ):
        _reject(CopywriterValidationErrorCode.REQUIRED_COPY)
    _validate_lengths(packet, draft)
    slot_names = tuple(
        slot.name.strip()
        for slot in packet.slots
        if (
            len(slot.name.strip()) >= 2
            and slot.name.strip().casefold()
            not in _PRODUCT_NAME_PLACEHOLDERS
        )
    )
    allowed_category_profiles = frozenset(
        slot.category_profile for slot in packet.slots
    )
    locked_atoms: list[str] = []
    for slot in packet.slots:
        approved_text = " ".join(
            fact.plain_meaning.casefold()
            for fact in slot.approved_soft_facts
        )
        locked_atoms.extend(
            fact.display_value
            for fact in slot.locked_facts
            if fact.kind
            in {
                "package_warning",
                "merchant_quote",
                "consumer_quote",
            }
            and fact.display_value.casefold() not in approved_text
        )
        locked_atoms.extend(
            caution.text for caution in slot.required_cautions
        )
    shared_validation_args = {
        "slot_names": slot_names,
        "locked_atoms": tuple(locked_atoms),
        "allowed_category_profiles": allowed_category_profiles,
        "forbid_product_introduction": bool(packet.slots),
    }
    _validate_text(
        draft.summary_copy.text,
        **shared_validation_args,
    )
    for item in draft.product_copy:
        for block in (item.positioning, item.advisor_reason):
            _validate_text(
                block.text,
                **shared_validation_args,
            )
    if draft.closing_copy is not None:
        _validate_text(
            draft.closing_copy.text,
            **shared_validation_args,
        )
    return draft


def _validate_section_draft(
    packet: PresentationPacket,
    draft: CopywriterDraft,
) -> ValidatedCopywriterDraft:
    specs = build_copywriter_section_specs(packet)
    expected = tuple((spec.kind, spec.slot_id) for spec in specs)
    actual = tuple(
        (section.kind, section.slot_id)
        for section in draft.sections
    )
    if actual != expected:
        _reject(CopywriterValidationErrorCode.SLOT_MISMATCH)
    slot_by_id = {slot.slot_id: slot for slot in packet.slots}
    for spec, section in zip(specs, draft.sections, strict=True):
        _validate_section_evidence(
            packet=packet,
            spec=spec,
            section=section,
            slot_by_id=slot_by_id,
        )
        _validate_section_attribution(
            packet=packet,
            spec=spec,
            section=section,
        )
    _validate_required_dimension_coverage(
        packet=packet,
        specs=specs,
        sections=draft.sections,
    )
    _validate_section_lengths(packet, specs, draft.sections)
    _validate_section_public_text(packet, draft.sections)
    return draft


def _validate_section_evidence(
    *,
    packet: PresentationPacket,
    spec: CopywriterSectionSpec,
    section: CopywriterSection,
    slot_by_id,
) -> None:
    if spec.content_source == "constraints_only":
        if (
            section.content.used_fact_ids
            or (
                section.advisor_reason is not None
                and section.advisor_reason.used_fact_ids
            )
        ):
            _reject(CopywriterValidationErrorCode.FACT_ID_MISMATCH)
    slot_product_id = (
        slot_by_id[spec.slot_id].product_id
        if spec.slot_id is not None
        else None
    )
    try:
        validate_copy_evidence(
            packet=packet,
            location=spec.evidence_location,
            slot_product_id=slot_product_id,
            used_fact_ids=section.content.used_fact_ids,
            used_constraint_ids=section.content.used_constraint_ids,
        )
        if section.advisor_reason is not None:
            validate_copy_evidence(
                packet=packet,
                location="recommendation.advisor_reason",
                slot_product_id=slot_product_id,
                used_fact_ids=section.advisor_reason.used_fact_ids,
                used_constraint_ids=(
                    section.advisor_reason.used_constraint_ids
                ),
            )
    except CopyEvidenceError:
        _reject(CopywriterValidationErrorCode.FACT_ID_MISMATCH)


def _validate_required_dimension_coverage(
    *,
    packet: PresentationPacket,
    specs: tuple[CopywriterSectionSpec, ...],
    sections: tuple[CopywriterSection, ...],
) -> None:
    facts_by_id = {
        fact.fact_id: fact
        for slot in packet.slots
        for fact in slot.approved_soft_facts
    }
    used_fact_ids = {
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
    required_dimensions = tuple(
        dict.fromkeys(
            dimension
            for spec in specs
            if spec.content_source == "approved_facts"
            for dimension in spec.required_dimension_ids
        )
    )
    for dimension in required_dimensions:
        eligible = {
            fact_id
            for spec in specs
            if spec.content_source == "approved_facts"
            for fact_id in spec.allowed_fact_ids
            if (
                fact_id in facts_by_id
                and _fact_covers_dimension(
                    facts_by_id[fact_id],
                    dimension,
                )
            )
        }
        if eligible and not (eligible & used_fact_ids):
            _reject(CopywriterValidationErrorCode.FACT_COVERAGE)
    for spec, section in zip(specs, sections, strict=True):
        if (
            spec.content_source != "approved_facts"
            or spec.kind != "product"
            or not spec.allowed_fact_ids
        ):
            continue
        section_fact_ids = {
            *section.content.used_fact_ids,
            *(
                section.advisor_reason.used_fact_ids
                if section.advisor_reason is not None
                else ()
            ),
        }
        if not section_fact_ids:
            _reject(CopywriterValidationErrorCode.FACT_COVERAGE)


def _fact_covers_dimension(fact, dimension_id: str) -> bool:
    if "." not in dimension_id:
        return fact.field_key == dimension_id
    return dimension_id in fact.dimension_ids


def _validate_section_attribution(
    *,
    packet: PresentationPacket,
    spec: CopywriterSectionSpec,
    section: CopywriterSection,
) -> None:
    facts_by_id = {
        fact.fact_id: fact
        for slot in packet.slots
        for fact in slot.approved_soft_facts
    }
    used = {
        *section.content.used_fact_ids,
        *(
            section.advisor_reason.used_fact_ids
            if section.advisor_reason is not None
            else ()
        ),
    }
    facts = tuple(
        facts_by_id[fact_id]
        for fact_id in used
        if fact_id in facts_by_id
    )
    text = " ".join(
        value
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
    _validate_fact_attribution(facts, text)


def _validate_section_lengths(
    packet: PresentationPacket,
    specs: tuple[CopywriterSectionSpec, ...],
    sections: tuple[CopywriterSection, ...],
) -> None:
    for spec, section in zip(specs, sections, strict=True):
        if len(section.content.text) > spec.copy_max_chars:
            _reject(CopywriterValidationErrorCode.LENGTH)
        if (
            section.advisor_reason is not None
            and len(section.advisor_reason.text)
            > packet.copy_budget.advisor_reason_max_chars
        ):
            _reject(CopywriterValidationErrorCode.LENGTH)


def _validate_section_public_text(
    packet: PresentationPacket,
    sections: tuple[CopywriterSection, ...],
) -> None:
    slot_names = tuple(
        slot.name.strip()
        for slot in packet.slots
        if (
            len(slot.name.strip()) >= 2
            and slot.name.strip().casefold()
            not in _PRODUCT_NAME_PLACEHOLDERS
        )
    )
    locked_atoms: list[str] = []
    for slot in packet.slots:
        approved_text = " ".join(
            fact.plain_meaning.casefold()
            for fact in slot.approved_soft_facts
        )
        locked_atoms.extend(
            fact.display_value
            for fact in slot.locked_facts
            if fact.kind
            in {
                "package_warning",
                "merchant_quote",
                "consumer_quote",
            }
            and fact.display_value.casefold() not in approved_text
        )
        locked_atoms.extend(
            caution.text for caution in slot.required_cautions
        )
    shared_validation_args = {
        "slot_names": slot_names,
        "locked_atoms": tuple(locked_atoms),
        "allowed_category_profiles": frozenset(
            slot.category_profile for slot in packet.slots
        ),
        "forbid_product_introduction": bool(packet.slots),
    }
    for section in sections:
        _validate_text(section.content.text, **shared_validation_args)
        if section.advisor_reason is not None:
            _validate_text(
                section.advisor_reason.text,
                **shared_validation_args,
            )


def is_safe_soft_fact_text(
    text: str,
    *,
    attribution: str | None = None,
    field_key: str | None = None,
) -> bool:
    if not isinstance(text, str) or not text.strip():
        return False
    return not any(
        pattern.search(text)
        for pattern in (
            _PRODUCT_INTRODUCTION,
            _SAFETY_GUARANTEE,
            _MARKUP,
        )
    )


def _validate_winner_claims(
    packet: PresentationPacket,
    draft: CopywriterDraft,
) -> None:
    if any(
        block.winner_claim == "selected"
        for block in _iter_copy_blocks(draft)
    ) and (
        packet.winner_status not in _AUTHORIZED_WINNER_STATUSES
    ):
        _reject(CopywriterValidationErrorCode.WINNER_LANGUAGE)


def _iter_copy_blocks(draft: CopywriterDraft):
    if draft.summary_copy is None:
        for section in draft.sections:
            yield section.content
            if section.advisor_reason is not None:
                yield section.advisor_reason
        return
    yield draft.summary_copy
    for item in draft.product_copy:
        yield item.positioning
        yield item.advisor_reason
    if draft.closing_copy is not None:
        yield draft.closing_copy


def _validate_product_attribution(
    slot,
    item,
) -> None:
    used = {
        *item.positioning.used_fact_ids,
        *item.advisor_reason.used_fact_ids,
    }
    facts = tuple(
        fact for fact in slot.approved_soft_facts if fact.fact_id in used
    )
    _validate_fact_attribution(
        facts,
        f"{item.positioning.text} {item.advisor_reason.text}",
    )


def _validate_shared_attribution(
    packet: PresentationPacket,
    block: SourceTaggedCopy,
) -> None:
    used = set(block.used_fact_ids)
    facts = tuple(
        fact
        for slot in packet.slots
        for fact in slot.approved_soft_facts
        if fact.fact_id in used
    )
    _validate_fact_attribution(facts, block.text)


def _validate_fact_attribution(facts, text: str) -> None:
    if any(fact.attribution == "merchant_claim" for fact in facts):
        if not _MERCHANT_ATTRIBUTION.search(text):
            _reject(CopywriterValidationErrorCode.ATTRIBUTION)
    if any(fact.attribution == "consumer_report" for fact in facts):
        if not _CONSUMER_ATTRIBUTION.search(text):
            _reject(CopywriterValidationErrorCode.ATTRIBUTION)


def _validate_lengths(
    packet: PresentationPacket,
    draft: CopywriterDraft,
) -> None:
    budget = packet.copy_budget
    if len(draft.summary_copy.text) > budget.summary_max_chars:
        _reject(CopywriterValidationErrorCode.LENGTH)
    if (
        draft.closing_copy is not None
        and len(draft.closing_copy.text) > budget.closing_max_chars
    ):
        _reject(CopywriterValidationErrorCode.LENGTH)
    for item in draft.product_copy:
        if len(item.positioning.text) > budget.positioning_max_chars:
            _reject(CopywriterValidationErrorCode.LENGTH)
        if (
            len(item.advisor_reason.text)
            > budget.advisor_reason_max_chars
        ):
            _reject(CopywriterValidationErrorCode.LENGTH)


def _validate_text(
    text: str,
    *,
    slot_names: tuple[str, ...],
    locked_atoms: tuple[str, ...],
    allowed_category_profiles: frozenset[str],
    forbid_product_introduction: bool,
) -> None:
    try:
        validate_final_public_text(text)
    except PublicLanguageError:
        _reject(CopywriterValidationErrorCode.INTERNAL_LANGUAGE)
    if _INTERNAL_PUBLIC_LANGUAGE.search(text):
        _reject(CopywriterValidationErrorCode.INTERNAL_LANGUAGE)
    if _MARKUP.search(text):
        _reject(CopywriterValidationErrorCode.MARKUP)
    if any(
        atom.strip()
        and atom.strip().casefold() in text.casefold()
        for atom in locked_atoms
    ):
        _reject(CopywriterValidationErrorCode.HARD_FACT)
    if any(name in text for name in slot_names):
        _reject(CopywriterValidationErrorCode.PRODUCT_NAME)
    if _has_mismatched_category_assertion(
        text,
        allowed_category_profiles=allowed_category_profiles,
    ):
        _reject(CopywriterValidationErrorCode.CATEGORY_MISMATCH)
    if (
        forbid_product_introduction
        and _PRODUCT_INTRODUCTION.search(text)
    ):
        _reject(CopywriterValidationErrorCode.PRODUCT_NAME)
    if _SAFETY_GUARANTEE.search(text):
        _reject(CopywriterValidationErrorCode.SAFETY_GUARANTEE)


def _has_mismatched_category_assertion(
    text: str,
    *,
    allowed_category_profiles: frozenset[str],
) -> bool:
    if not allowed_category_profiles:
        return False
    for profile, category_pattern in _CATEGORY_TERMS.items():
        if profile in allowed_category_profiles:
            continue
        category = f"(?:{category_pattern.pattern})"
        assertions = (
            rf"(?:一|两|三|四|多)款[^，。！？\n]{{0,8}}{category}",
            rf"(?:它|当前商品|这个产品|该产品|这款|该款)"
            rf"(?:是|属于|定位为|作为|就是)"
            rf"[^，。！？\n]{{0,8}}{category}",
            rf"(?:买|选|推荐|考虑|比较|看看|入手)"
            rf"[^，。！？\n]{{0,8}}{category}",
        )
        if any(re.search(pattern, text) for pattern in assertions):
            return True
    return False


def _reject(code: CopywriterValidationErrorCode) -> None:
    raise CopywriterValidationError(code)


__all__ = [
    "CopywriterValidationError",
    "CopywriterValidationErrorCode",
    "ValidatedCopywriterDraft",
    "is_safe_soft_fact_text",
    "validate_copywriter_draft",
]
