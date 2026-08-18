from __future__ import annotations

from enum import Enum
import re

from app.guide.presentation.copywriter_contracts import (
    CopywriterDraft,
    PresentationPacket,
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


_DIGIT = re.compile(r"[0-9０-９]")
_CHINESE_QUANTITY = re.compile(
    r"[零〇一二两三四五六七八九十百千万]+"
    r"(?:元|天|周|个月|月|年|小时|分钟|秒|人|位|名|例|成)"
)
_PROTECTION_VALUE = re.compile(r"\bspf\s*\d*|\bpa\s*\++", re.IGNORECASE)
_INGREDIENT = re.compile(
    r"烟酰胺|视黄醇|水杨酸|果酸|神经酰胺|玻色因|玻尿酸|透明质酸|"
    r"二氧化钛|氧化锌|酒精|乙醇|香精|防腐剂"
)
_HARD_FACT_TOKEN = re.compile(
    r"[0-9０-９]+(?:\s*(?:[%％]|元|天|周|个月|月|年|小时|分钟|秒|"
    r"人|位|名|例|成|款|种|ml|mL|ML|毫升|滴))?"
)
_HARD_FACT_RANGE = re.compile(
    r"[0-9０-９]+\s*(?:-|－|—|~|～|到|至)\s*"
    r"[0-9０-９]+\s*(?:元|块)?"
)
_BARE_DIGIT = re.compile(r"[0-9０-９]+")
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
_WINNER_LANGUAGE = re.compile(
    r"最佳|首选|最适合|唯一推荐|闭眼入|稳赢|第一选择"
)
_NEGATED_WINNER_CONTEXT = re.compile(
    r"(?:证据|信息|条件)?"
    r"(?:仍?不(?:足以|够|能|可|应|是|代表)|无法|未能|没有|是否)"
    r"[^，。！？\n]{0,16}$"
)
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
_APPROVED_HARD_FACT_FIELDS = frozenset({
    "efficacy",
    "ingredients_present",
})
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

    expected_slots = tuple(slot.slot_id for slot in packet.slots)
    actual_slots = tuple(item.slot_id for item in draft.product_copy)
    if actual_slots != expected_slots:
        _reject(CopywriterValidationErrorCode.SLOT_MISMATCH)

    slot_by_id = {slot.slot_id: slot for slot in packet.slots}
    for item in draft.product_copy:
        slot = slot_by_id[item.slot_id]
        allowed_ids = {
            fact.fact_id for fact in slot.approved_soft_facts
        }
        if not set(item.used_soft_fact_ids).issubset(allowed_ids):
            _reject(CopywriterValidationErrorCode.FACT_ID_MISMATCH)
        required_count = 1 if slot.approved_soft_facts else 0
        if len(item.used_soft_fact_ids) < required_count:
            _reject(CopywriterValidationErrorCode.FACT_COVERAGE)
        _validate_attribution(slot, item)

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
        "winner_authorized": (
            packet.winner_status in _AUTHORIZED_WINNER_STATUSES
        ),
        "forbid_product_introduction": bool(packet.slots),
    }
    _validate_text(
        draft.summary_copy,
        authorized_hard_fact_text=_summary_authorized_hard_fact_text(
            packet
        ),
        **shared_validation_args,
    )
    for item in draft.product_copy:
        slot = slot_by_id[item.slot_id]
        authorized_hard_fact_text = _authorized_hard_fact_text(
            slot.approved_soft_facts
        )
        for text in (item.positioning, item.advisor_reason):
            _validate_text(
                text,
                authorized_hard_fact_text=authorized_hard_fact_text,
                **shared_validation_args,
            )
    if draft.closing_copy is not None:
        _validate_text(
            draft.closing_copy,
            authorized_hard_fact_text=_summary_authorized_hard_fact_text(
                packet
            ),
            **shared_validation_args,
        )
    return draft


def is_safe_soft_fact_text(
    text: str,
    *,
    attribution: str | None = None,
    field_key: str | None = None,
) -> bool:
    if not isinstance(text, str) or not text.strip():
        return False
    authorized_hard_fact_text = (
        text
        if field_key in _APPROVED_HARD_FACT_FIELDS
        else ""
    )
    if _has_unauthorized_hard_fact(
        text,
        authorized_text=authorized_hard_fact_text,
    ):
        return False
    if _has_unauthorized_ingredient(
        text,
        authorized_text=authorized_hard_fact_text,
    ):
        return False
    return not any(
        pattern.search(text)
        for pattern in (
            _PROTECTION_VALUE,
            _PRODUCT_INTRODUCTION,
            _WINNER_LANGUAGE,
            _SAFETY_GUARANTEE,
            _MARKUP,
        )
    )


def _validate_attribution(slot, item) -> None:
    used = set(item.used_soft_fact_ids)
    facts = tuple(
        fact for fact in slot.approved_soft_facts if fact.fact_id in used
    )
    text = f"{item.positioning} {item.advisor_reason}"
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
    if len(draft.summary_copy) > budget.summary_max_chars:
        _reject(CopywriterValidationErrorCode.LENGTH)
    if (
        draft.closing_copy is not None
        and len(draft.closing_copy) > budget.closing_max_chars
    ):
        _reject(CopywriterValidationErrorCode.LENGTH)
    for item in draft.product_copy:
        if len(item.positioning) > budget.positioning_max_chars:
            _reject(CopywriterValidationErrorCode.LENGTH)
        if len(item.advisor_reason) > budget.advisor_reason_max_chars:
            _reject(CopywriterValidationErrorCode.LENGTH)


def _validate_text(
    text: str,
    *,
    slot_names: tuple[str, ...],
    locked_atoms: tuple[str, ...],
    allowed_category_profiles: frozenset[str],
    winner_authorized: bool,
    forbid_product_introduction: bool,
    authorized_hard_fact_text: str,
) -> None:
    if _INTERNAL_PUBLIC_LANGUAGE.search(text):
        _reject(CopywriterValidationErrorCode.INTERNAL_LANGUAGE)
    if _MARKUP.search(text):
        _reject(CopywriterValidationErrorCode.MARKUP)
    if _has_unauthorized_hard_fact(
        text,
        authorized_text=authorized_hard_fact_text,
    ):
        _reject(CopywriterValidationErrorCode.HARD_FACT)
    if _PROTECTION_VALUE.search(text):
        _reject(CopywriterValidationErrorCode.HARD_FACT)
    if any(
        atom.strip()
        and atom.strip().casefold() in text.casefold()
        for atom in locked_atoms
    ):
        _reject(CopywriterValidationErrorCode.HARD_FACT)
    if _has_unauthorized_ingredient(
        text,
        authorized_text=authorized_hard_fact_text,
    ):
        _reject(CopywriterValidationErrorCode.INGREDIENT)
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
    if (
        not winner_authorized
        and _has_positive_winner_language(text)
    ):
        _reject(CopywriterValidationErrorCode.WINNER_LANGUAGE)
    if _SAFETY_GUARANTEE.search(text):
        _reject(CopywriterValidationErrorCode.SAFETY_GUARANTEE)


def _has_positive_winner_language(text: str) -> bool:
    for match in _WINNER_LANGUAGE.finditer(text):
        context = text[max(0, match.start() - 24):match.start()]
        if _NEGATED_WINNER_CONTEXT.search(context):
            continue
        return True
    return False


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


def _summary_authorized_hard_fact_text(packet: PresentationPacket) -> str:
    count = len(packet.slots)
    structural_count = (
        f"{count}款"
        if count > 0
        else ""
    )
    return " ".join(
        value
        for value in (
            packet.user_need_summary,
            structural_count,
        )
        if value
    )


def _authorized_hard_fact_text(facts: tuple[object, ...]) -> str:
    return " ".join(
        fact.plain_meaning
        for fact in facts
        if getattr(fact, "field_key", None) in _APPROVED_HARD_FACT_FIELDS
    )


def _has_unauthorized_hard_fact(
    text: str,
    *,
    authorized_text: str,
) -> bool:
    if _PROTECTION_VALUE.search(text):
        return True
    authorized_spans: list[tuple[int, int]] = []
    for match in _HARD_FACT_RANGE.finditer(text):
        token = match.group(0).strip()
        if not _is_authorized_numeric_range(
            token,
            authorized_text=authorized_text,
        ):
            return True
        authorized_spans.append(match.span())
    for pattern in (_HARD_FACT_TOKEN, _CHINESE_QUANTITY):
        for match in pattern.finditer(text):
            if _span_is_within(match.span(), authorized_spans):
                continue
            token = match.group(0).strip()
            if _BARE_DIGIT.fullmatch(token):
                return True
            if token and not _is_authorized_fragment(
                token,
                authorized_text=authorized_text,
            ):
                return True
    return False


def _has_unauthorized_ingredient(
    text: str,
    *,
    authorized_text: str,
) -> bool:
    return any(
        not _is_authorized_fragment(
            match.group(0),
            authorized_text=authorized_text,
        )
        for match in _INGREDIENT.finditer(text)
    )


def _is_authorized_fragment(
    fragment: str,
    *,
    authorized_text: str,
) -> bool:
    if not authorized_text:
        return False
    return _compact(fragment) in _compact(authorized_text)


def _is_authorized_numeric_range(
    fragment: str,
    *,
    authorized_text: str,
) -> bool:
    if not authorized_text:
        return False
    values = re.findall(r"[0-9０-９]+", _compact(fragment))
    if len(values) != 2:
        return False
    pattern = (
        re.escape(values[0])
        + r"(?:-|－|—|~|～|到|至)?"
        + re.escape(values[1])
        + r"(?:元|块)?"
    )
    return re.search(pattern, _compact(authorized_text)) is not None


def _span_is_within(
    span: tuple[int, int],
    containers: list[tuple[int, int]],
) -> bool:
    start, end = span
    return any(
        container_start <= start and end <= container_end
        for container_start, container_end in containers
    )


def _compact(value: str) -> str:
    return _SPACELESS.sub("", value).casefold()


_SPACELESS = re.compile(r"\s+")


def _reject(code: CopywriterValidationErrorCode) -> None:
    raise CopywriterValidationError(code)


__all__ = [
    "CopywriterValidationError",
    "CopywriterValidationErrorCode",
    "ValidatedCopywriterDraft",
    "is_safe_soft_fact_text",
    "validate_copywriter_draft",
]
