import re
from typing import Protocol

from app.guide.decision.contracts import FactState
from app.guide.decision.image_suitability_contracts import (
    ImageSuitabilityDecisionInput,
    ImageSuitabilityDecisionResult,
    ResolvedSuitabilityContext,
    SuitabilityCardIntent,
    SuitabilityContextClaims,
    SuitabilityContextResolution,
    SuitabilityEvaluatedSkinFact,
    context_precedence,
)
from app.guide.understanding.contracts import SkinTarget


_SKIN_ALIASES = {
    SkinTarget.OILY_SENSITIVE: (
        "油敏肌",
        "油敏皮",
        "油敏",
        "oily sensitive skin",
        "sensitive oily skin",
    ),
    SkinTarget.OILY: (
        "油性肌肤",
        "油性肤质",
        "油性皮肤",
        "油皮",
        "oily skin",
    ),
    SkinTarget.DRY: (
        "干性肌肤",
        "干性肤质",
        "干性皮肤",
        "干皮",
        "dry skin",
    ),
    SkinTarget.COMBINATION: (
        "混合性肌肤",
        "混合性肤质",
        "混合性皮肤",
        "混合肌",
        "混油皮",
        "混油肤质",
        "混油",
        "混干",
        "combination skin",
    ),
    SkinTarget.SENSITIVE: (
        "敏感性肤质",
        "敏感性肌肤",
        "敏感性皮肤",
        "敏感肌",
        "敏皮",
        "sensitive skin",
    ),
    SkinTarget.NORMAL: (
        "中性肌肤",
        "中性肤质",
        "中性皮肤",
        "中性",
        "normal skin",
    ),
}
_CLAUSE_SEPARATOR = r"[\s:：,，;；()（）\[\]【】\-]*"
_CLAUSE_SPLIT_PATTERN = re.compile(
    r"[,，;；。!?！？()（）\[\]【】]+|"
    r"(?:但是|不过|然而|但)|"
    r"\b(?:however|whereas|while|but)\b",
    re.IGNORECASE,
)
_UNCERTAINTY_OR_QUALIFIER_PATTERN = re.compile(
    r"是否|能否|待确认|未确认|不确定|未知|不明|未证实|酌情|"
    r"不太|不怎么|不一定|未必|并非|并不是|极度|除外|慎用|谨慎|"
    r"\b(?:whether|uncertain|unknown|unconfirmed|unverified|"
    r"not\s+(?:known|confirmed|verified|proven|entirely|always|"
    r"particularly)|pending\s+confirmation|possibly|potentially|"
    r"maybe|may|might|could|hardly|extremely|except|caution)\b",
    re.IGNORECASE,
)


class ImageSuitabilityDecisionPort(Protocol):
    def decide(
        self,
        request: ImageSuitabilityDecisionInput,
    ) -> ImageSuitabilityDecisionResult: ...


def resolve_suitability_context(
    claims: SuitabilityContextClaims,
) -> SuitabilityContextResolution:
    if not claims.claims:
        return SuitabilityContextResolution(kind="absent")

    selected = min(
        claims.claims,
        key=lambda claim: context_precedence(
            claim.provenance.source_kind
        ),
    )
    try:
        skin_target = SkinTarget(selected.skin_target)
    except ValueError:
        return SuitabilityContextResolution(
            kind="unsupported",
            source=selected.provenance.source_kind,
            unsupported_value=selected.skin_target,
        )
    return SuitabilityContextResolution(
        kind="resolved",
        context=ResolvedSuitabilityContext(
            precedence=context_precedence(
                selected.provenance.source_kind
            ),
            skin_target=skin_target,
            provenance=selected.provenance,
        ),
    )


class ImageSuitabilityDecisionFoundation:
    def decide(
        self,
        request: ImageSuitabilityDecisionInput,
    ) -> ImageSuitabilityDecisionResult:
        evaluated = SuitabilityEvaluatedSkinFact(
            state=request.facts.suitable_skin_state,
            values=request.facts.suitable_skin,
            source_refs=request.facts.suitable_skin_source_refs,
        )
        status = "insufficient_evidence"
        reason = _insufficient_reason(evaluated)
        if evaluated.source_refs:
            if (
                evaluated.state is FactState.KNOWN
                and evaluated.values is not None
            ):
                match = _skin_match(
                    evaluated.values,
                    request.context.skin_target,
                )
                if match == "matched":
                    status = "suitable"
                    reason = "canonical_skin_match"
                elif match == "explicit_exclusion":
                    status = "not_suitable"
                    reason = "canonical_skin_explicit_exclusion"
            elif evaluated.state is FactState.NOT_APPLICABLE:
                status = "not_suitable"
                reason = "canonical_skin_not_applicable"
        return ImageSuitabilityDecisionResult(
            status=status,
            reason=reason,
            reference=request.reference,
            context=request.context,
            evaluated_skin_fact=evaluated,
            evidence_refs=(
                request.context.evidence_ref,
                *evaluated.source_refs,
            ),
            card_intent=SuitabilityCardIntent(
                mode="single",
                visible_product_ids=(request.reference.product_id,),
                reason="product",
            ),
        )


def _skin_match(
    values: tuple[str, ...],
    target: SkinTarget,
) -> str:
    normalized = tuple(_normalize_skin_text(value) for value in values)
    clauses = tuple(
        clause
        for value in normalized
        for clause in _split_skin_clauses(value)
    )
    negative_targets = (
        (target, SkinTarget.OILY, SkinTarget.SENSITIVE)
        if target is SkinTarget.OILY_SENSITIVE
        else (target,)
    )
    if any(
        _has_explicit_negative(clause, candidate)
        for clause in clauses
        for candidate in negative_targets
    ):
        return "explicit_exclusion"
    if any(
        _has_uncertainty_or_qualifier(clause, candidate)
        for clause in clauses
        for candidate in negative_targets
    ):
        return "indeterminate"

    if any(_has_positive(clause, target) for clause in clauses):
        return "matched"
    if target is SkinTarget.OILY_SENSITIVE:
        oily_match = any(
            _has_positive(clause, SkinTarget.OILY)
            for clause in clauses
        )
        sensitive_match = any(
            _has_positive(clause, SkinTarget.SENSITIVE)
            for clause in clauses
        )
        if oily_match and sensitive_match:
            return "matched"
    return "indeterminate"


def _normalize_skin_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.casefold()).strip()


def _split_skin_clauses(value: str) -> tuple[str, ...]:
    clauses: list[str] = []
    for part in _CLAUSE_SPLIT_PATTERN.split(value):
        part = part.strip()
        if not part:
            continue
        if clauses and not _contains_skin_alias(part):
            clauses[-1] = f"{clauses[-1]} {part}"
        else:
            clauses.append(part)
    return tuple(clauses)


def _contains_skin_alias(value: str) -> bool:
    return any(
        re.search(_skin_alias_pattern(target), value)
        for target in SkinTarget
    )


def _skin_alias_pattern(target: SkinTarget) -> str:
    patterns: list[str] = []
    for alias in sorted(_SKIN_ALIASES[target], key=len, reverse=True):
        if alias.isascii():
            words = re.split(r"[\s-]+", alias)
            body = r"[\s-]+".join(re.escape(word) for word in words)
            patterns.append(rf"(?<![a-z]){body}(?![a-z])")
        else:
            patterns.append(re.escape(alias))
    return "(?:" + "|".join(patterns) + ")"


def _is_exact_skin_alias(
    value: str,
    target: SkinTarget,
) -> bool:
    return value in {
        _normalize_skin_text(alias) for alias in _SKIN_ALIASES[target]
    }


def _has_positive(
    value: str,
    target: SkinTarget,
) -> bool:
    return _is_exact_skin_alias(value, target) or _has_explicit_positive(
        value,
        target,
    )


def _has_uncertainty_or_qualifier(
    value: str,
    target: SkinTarget,
) -> bool:
    return bool(
        re.search(_skin_alias_pattern(target), value, re.IGNORECASE)
        and _UNCERTAINTY_OR_QUALIFIER_PATTERN.search(value)
    )


def _has_explicit_negative(
    value: str,
    target: SkinTarget,
) -> bool:
    alias = _skin_alias_pattern(target)
    chinese_prefix = (
        rf"(?:不适用(?:于)?|不适合(?:于)?|不建议|不推荐|避免|禁用|"
        rf"禁止)(?:给|由|在)?{_CLAUSE_SEPARATOR}{alias}"
        rf"(?:人群)?(?:使用|适用|用)?"
    )
    chinese_suffix = (
        rf"{alias}(?:人群)?{_CLAUSE_SEPARATOR}"
        rf"(?:不适用|不适合|慎用|谨慎使用|建议慎用|"
        rf"不建议(?:使用)?|不推荐(?:使用)?|(?:应|请)?避免(?:使用)?|"
        rf"不宜(?:使用)?|不可用|勿用|禁用|禁止(?:使用)?|除外)"
    )
    chinese_exclusion = rf"除{_CLAUSE_SEPARATOR}{alias}\s*外"
    english_prefix = (
        rf"(?<![a-z])(?:not\s+(?:suitable|recommended|safe|appropriate)"
        rf"\s+for|unsuitable\s+for|not\s+for|"
        rf"avoid(?:\s+use)?(?:\s+(?:on|for))?|"
        rf"do\s+not\s+use(?:\s+(?:on|for))?|prohibited\s+for|"
        rf"should\s+not\s+be\s+used\s+(?:on|for)|"
        rf"contraindicated\s+for|excluded\s+for)\s*{alias}"
    )
    english_suffix = (
        rf"{alias}[\s:,\-]*(?:is\s+)?"
        rf"(?:not\s+(?:suitable|recommended|safe|appropriate)|"
        rf"unsuitable|use\s+with\s+caution|"
        rf"should\s+(?:be\s+used\s+with\s+caution|avoid(?:\s+use)?)|"
        rf"prohibited|contraindicated|excluded)(?![a-z])"
    )
    english_exclusion = (
        rf"(?:.+\s+)?except(?:\s+for)?\s+{alias}"
    )
    return any(
        re.fullmatch(pattern, value, re.IGNORECASE)
        for pattern in (
            chinese_prefix,
            chinese_suffix,
            chinese_exclusion,
            english_prefix,
            english_suffix,
            english_exclusion,
        )
    )


def _has_explicit_positive(
    value: str,
    target: SkinTarget,
) -> bool:
    alias = _skin_alias_pattern(target)
    chinese_prefix = (
        rf"(?:适合|适用于|推荐给|可用于)"
        rf"{_CLAUSE_SEPARATOR}{alias}(?:人群)?(?:使用)?"
    )
    chinese_suffix = (
        rf"{alias}(?:人群)?{_CLAUSE_SEPARATOR}"
        rf"(?:适用|可用|友好|可以使用|能用|推荐使用)"
    )
    english_prefix = (
        rf"(?<![a-z])(?:suitable|safe|recommended|appropriate)"
        rf"\s+for\s+{alias}"
    )
    english_suffix = (
        rf"{alias}[\s:,\-]*(?:friendly|compatible|suitable|safe|"
        rf"recommended)(?![a-z])"
    )
    return any(
        re.fullmatch(pattern, value, re.IGNORECASE)
        for pattern in (
            chinese_prefix,
            chinese_suffix,
            english_prefix,
            english_suffix,
        )
    )


def _insufficient_reason(
    fact: SuitabilityEvaluatedSkinFact,
) -> str:
    if not fact.source_refs:
        return "canonical_skin_unaudited"
    if fact.state is FactState.UNKNOWN:
        return "canonical_skin_unknown"
    if fact.state is FactState.CONFLICT:
        return "canonical_skin_conflict"
    if fact.state is FactState.NOT_APPLICABLE:
        return "canonical_skin_not_applicable"
    return "canonical_skin_indeterminate"
