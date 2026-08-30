from __future__ import annotations

from itertools import combinations

from app.guide.intent.responsibility_matrix import Responsibility
from app.guide.presentation.copywriter_contracts import (
    ApprovedSoftFact,
    CopywriterDraft,
    CopywriterSection,
    CopywriterSectionSpec,
    PresentationMode,
    PresentationPacket,
    SourceTaggedCopy,
    build_copywriter_section_specs,
)
from app.guide.presentation.copywriter_validation import (
    is_safe_soft_fact_text,
)


_SUMMARY_BY_MODE: dict[PresentationMode, str] = {
    "recommendation": (
        "结合你现在的预算和使用场景，我把各款优势与取舍分开说，"
        "方便你直接按需求选择。"
    ),
    "comparison": (
        "这几款走的路线不完全一样，先看与你最相关的差异，"
        "再按实际使用场景决定。"
    ),
    "single_product": (
        "这款的主打方向比较清楚，下面把与你当前需求相关的信息和"
        "使用提醒放在一起看。"
    ),
    "product_knowledge": (
        "关于这款商品，我直接回答你问的质地、用法或注意事项，"
        "不额外展开推荐。"
    ),
    "general_knowledge": (
        "先把这个概念讲清楚，再落到日常挑选和使用时真正需要注意的"
        "地方。"
    ),
    "followup": (
        "按你刚补充的信息继续看，这次只回答变化后的重点，"
        "不把上一轮内容重新讲一遍。"
    ),
    "revision": (
        "预算或偏好已经按这次说法更新，下面重新看更符合当前需求的"
        "几款。"
    ),
    "image_identity": (
        "图片里的商品身份能够确认后，我会直接结合商品资料回答；"
        "看不清的部分不会凭包装相似度猜。"
    ),
    "image_recommendation": (
        "我按图片里的商品路线找相近选择，同时把相似点和关键差异说"
        "清楚。"
    ),
    "image_suitability": (
        "先看图片对应商品的主打方向，再结合你当前的肤况和使用场景"
        "判断是否合适。"
    ),
    "image_comparison": (
        "我按图片顺序比较这几款，先看最影响选择的差异，再给具体"
        "场景建议。"
    ),
    "consultation": (
        "我先整理目前能支持的观察；涉及诊断或治疗的部分不能在这里下结论。"
    ),
    "clarification": (
        "还需要补充一个关键信息，才能继续给出可靠结果。"
    ),
    "error": (
        "这次暂时没有得到可用结果，请稍后重试或换一种说法。"
    ),
}

_CLOSING_BY_MODE: dict[PresentationMode, str | None] = {
    "recommendation": (
        "日常使用更看重轻松顺手，就选肤感和场景更贴近的一款；"
        "若更在意功效完整度，再看品牌主打和使用提醒。"
    ),
    "comparison": (
        "更看重哪项，就优先选择对应路线；信息相同处不用勉强分高下。"
    ),
    "single_product": (
        "第一次使用可以从少量、低频开始，观察实际肤感后再决定是否"
        "继续。"
    ),
    "product_knowledge": None,
    "general_knowledge": None,
    "followup": (
        "后续继续追问时，我会沿用你刚确认的信息，不再带回已经修改的"
        "旧偏好。"
    ),
    "revision": (
        "这次结果以最新预算和偏好为准，可以直接从新的使用取舍里做"
        "决定。"
    ),
    "image_identity": (
        "如果图片关键信息不完整，可以补一张正面或标签清晰的照片。"
    ),
    "image_recommendation": (
        "选择时别只看包装相似度，优先看肤感、功效路线和预算是否真正"
        "符合你的需求。"
    ),
    "image_suitability": (
        "信息不足的部分先不下结论，必要时补充肤质或使用目标。"
    ),
    "image_comparison": (
        "怎么选取决于你更在意的差异，无法确认的部分不参与胜负判断。"
    ),
    "consultation": None,
    "clarification": None,
    "error": None,
}


def fallback_copy(packet: PresentationPacket) -> CopywriterDraft:
    if not isinstance(packet, PresentationPacket):
        raise TypeError("packet must be PresentationPacket")
    specs = build_copywriter_section_specs(packet)
    return CopywriterDraft(
        mode=packet.mode,
        sections=tuple(
            _fallback_section(packet, spec)
            for spec in specs
        ),
    )


def _fallback_section(
    packet: PresentationPacket,
    spec: CopywriterSectionSpec,
) -> CopywriterSection:
    if spec.kind == "product":
        if spec.slot_id is None:
            raise AssertionError("product writer spec requires slot")
        slot = next(
            slot
            for slot in packet.slots
            if slot.slot_id == spec.slot_id
        )
        content, advisor_reason = _fallback_product_section(
            packet,
            slot,
            required_dimensions=spec.required_dimension_ids,
        )
        return CopywriterSection(
            kind="product",
            slot_id=slot.slot_id,
            content=content,
            advisor_reason=advisor_reason,
        )
    if spec.kind in {"judgement", "answer"}:
        if spec.slot_id is None:
            raise AssertionError("bound writer spec requires slot")
        content = _fallback_fact_content(packet, spec)
        return CopywriterSection(
            kind=spec.kind,
            slot_id=spec.slot_id,
            content=content,
        )
    if spec.content_source != "constraints_only":
        raise AssertionError(
            "non-product factual writer section is unsupported"
        )
    if spec.kind == "closing":
        value = _CLOSING_BY_MODE[packet.mode]
        if value is None:
            raise AssertionError("closing writer spec requires fallback copy")
        return CopywriterSection(
            kind="closing",
            content=SourceTaggedCopy(
                text=_bounded(value, spec.copy_max_chars),
            ),
        )
    return CopywriterSection(
        kind=spec.kind,
        content=SourceTaggedCopy(
            text=_bounded(
                _SUMMARY_BY_MODE[packet.mode],
                spec.copy_max_chars,
            ),
        ),
    )


def _fallback_fact_content(
    packet: PresentationPacket,
    spec: CopywriterSectionSpec,
) -> SourceTaggedCopy:
    facts_by_id = {
        fact.fact_id: fact
        for slot in packet.slots
        for fact in slot.approved_soft_facts
    }
    eligible_facts = tuple(
        facts_by_id[fact_id]
        for fact_id in spec.allowed_fact_ids
        if (
            fact_id in facts_by_id
            and is_safe_soft_fact_text(
                facts_by_id[fact_id].plain_meaning,
                attribution=facts_by_id[fact_id].attribution,
                field_key=facts_by_id[fact_id].field_key,
            )
        )
    )
    facts = _select_fallback_facts(
        eligible_facts,
        required_dimensions=spec.required_dimension_ids,
    )
    if not facts:
        return SourceTaggedCopy(
            text="当前可确认的信息不多，先结合下方商品资料判断。",
        )
    return SourceTaggedCopy(
        text=_bounded(
            _attributed_facts_text(facts),
            spec.copy_max_chars,
        ),
        used_fact_ids=tuple(fact.fact_id for fact in facts),
    )


def _fallback_product_section(
    packet: PresentationPacket,
    slot,
    *,
    required_dimensions: tuple[str, ...] = (),
) -> tuple[SourceTaggedCopy, SourceTaggedCopy]:
    generic_copy = packet.responsibility in {
        Responsibility.RECOMMENDATION,
        Responsibility.COMPARISON,
    }
    safe_facts = tuple(
        fact
        for fact in slot.approved_soft_facts
        if not generic_copy or fact.generic_copy_allowed
    )
    safe_facts = tuple(
        fact
        for fact in safe_facts
        if is_safe_soft_fact_text(
            fact.plain_meaning,
            attribution=fact.attribution,
            field_key=fact.field_key,
        )
    )
    facts = _select_fallback_facts(
        safe_facts,
        required_dimensions=required_dimensions,
    )
    if not facts:
        positioning_facts: tuple[ApprovedSoftFact, ...] = ()
        reason_facts: tuple[ApprovedSoftFact, ...] = ()
        positioning = "这款目前可确认的信息不多，先看下方整理出的商品资料。"
        reason = "是否合适还要结合你的使用场景和实际肤感。"
    else:
        (
            positioning_facts,
            reason_facts,
            meaning_limit,
        ) = _split_facts_for_budgets(
            facts,
            positioning_limit=packet.copy_budget.positioning_max_chars,
            reason_limit=packet.copy_budget.advisor_reason_max_chars,
        )
        positioning = _attributed_facts_text(
            positioning_facts,
            meaning_limit=meaning_limit,
        )
        reason = (
            _attributed_facts_text(
                reason_facts,
                meaning_limit=meaning_limit,
            )
            if reason_facts
            else "是否合适还要结合你的使用场景和实际肤感。"
        )
    return (
        SourceTaggedCopy(
            text=positioning,
            used_fact_ids=tuple(
                fact.fact_id for fact in positioning_facts
            ),
        ),
        SourceTaggedCopy(
            text=reason,
            used_fact_ids=tuple(
                fact.fact_id for fact in reason_facts
            ),
        ),
    )


def _split_facts_for_budgets(
    facts: tuple[ApprovedSoftFact, ...],
    *,
    positioning_limit: int,
    reason_limit: int,
) -> tuple[
    tuple[ApprovedSoftFact, ...],
    tuple[ApprovedSoftFact, ...],
    int | None,
]:
    for meaning_limit in (
        None,
        64,
        48,
        36,
        28,
        24,
        20,
        16,
        12,
        8,
    ):
        if len(facts) == 1:
            positioning = _attributed_facts_text(
                facts,
                meaning_limit=meaning_limit,
            )
            if len(positioning) <= positioning_limit:
                return facts, (), meaning_limit
            continue
        indexes = tuple(range(len(facts)))
        counts = sorted(
            range(1, len(facts)),
            key=lambda count: (abs((len(facts) / 2) - count), count),
        )
        for count in counts:
            for positioning_indexes in combinations(indexes, count):
                selected = set(positioning_indexes)
                positioning_facts = tuple(
                    fact
                    for index, fact in enumerate(facts)
                    if index in selected
                )
                reason_facts = tuple(
                    fact
                    for index, fact in enumerate(facts)
                    if index not in selected
                )
                if (
                    len(_attributed_facts_text(
                        positioning_facts,
                        meaning_limit=meaning_limit,
                    ))
                    <= positioning_limit
                    and len(_attributed_facts_text(
                        reason_facts,
                        meaning_limit=meaning_limit,
                    ))
                    <= reason_limit
                ):
                    return (
                        positioning_facts,
                        reason_facts,
                        meaning_limit,
                    )
    raise ValueError(
        "copy budget cannot fit required fallback fact coverage"
    )


def _select_fallback_facts(
    facts: tuple[ApprovedSoftFact, ...],
    *,
    required_dimensions: tuple[str, ...],
) -> tuple[ApprovedSoftFact, ...]:
    required_dimensions = tuple(dict.fromkeys(required_dimensions))
    selected: list[ApprovedSoftFact] = []
    for dimension_id in required_dimensions:
        fact = next(
            (
                item
                for item in facts
                if _fact_covers_dimension(item, dimension_id)
            ),
            None,
        )
        if fact is not None:
            selected.append(fact)
    if selected:
        return tuple({
            fact.fact_id: fact
            for fact in selected
        }.values())
    return facts[: min(2, len(facts))]


def _fact_covers_dimension(
    fact: ApprovedSoftFact,
    dimension_id: str,
) -> bool:
    if "." not in dimension_id:
        return fact.field_key == dimension_id
    return dimension_id in fact.dimension_ids


def _attributed_facts_text(
    facts: tuple[ApprovedSoftFact, ...],
    *,
    meaning_limit: int | None = None,
) -> str:
    grouped: dict[str, list[str]] = {}
    for fact in facts:
        grouped.setdefault(fact.attribution, []).append(
            _compact_fact_meaning(
                fact.plain_meaning,
                limit=meaning_limit,
            )
        )
    parts = []
    for attribution, meanings in grouped.items():
        joined = "；".join(meanings)
        if attribution == "merchant_claim":
            parts.append(f"品牌主打{joined}。")
        elif attribution == "consumer_report":
            parts.append(f"从限定样本的用户反馈看，{joined}。")
        else:
            parts.append(f"从现有商品信息看，{joined}。")
    return "".join(parts)


def _compact_fact_meaning(
    value: str,
    *,
    limit: int | None,
) -> str:
    prefixes = (
        "商家主打：",
        "商家资料：",
        "品牌主打：",
        "限定样本的用户反馈：",
        "已核对的信息显示：",
    )
    clauses = []
    for raw_clause in value.replace("；", ";").split(";"):
        clause = raw_clause.strip().rstrip("。；;")
        for prefix in prefixes:
            if clause.startswith(prefix):
                clause = clause[len(prefix):].strip()
                break
        if clause and clause not in clauses:
            clauses.append(clause)
    normalized = "；".join(clauses) or value.strip().rstrip("。；;")
    if limit is None or len(normalized) <= limit:
        return normalized
    return normalized[: limit - 1].rstrip("，,；;。 ") + "…"


def _bounded(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip("，,；;。 ") + "。"


def _bounded_optional(value: str | None, limit: int) -> str | None:
    return None if value is None else _bounded(value, limit)


__all__ = ["fallback_copy"]
