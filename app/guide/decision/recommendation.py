"""Slice 1 决策层：硬筛 + 稳定排序 + 出 DecisionResult。

原则（方案 A2）：
- 价格已知且满足预算才入选；价格 unknown/conflict 一律排除，不猜便宜。
- 肤质明确适合排前；肤质 unknown 保留但排后并标注缺失。
- 肤质明确不匹配直接排除，不能伪装成 unknown。
- 明确预算上限只在同档候选间按距离上限从近到远排序。
- 只读授权结构化字段，不读 raw 描述/评论/OCR。
- 决策层是唯一裁判：复用锁定的 deterministic 排序内核。
"""
from __future__ import annotations

from decimal import Decimal
import json
from typing import Literal

from app.guide.decision.contracts import (
    CandidateEvaluation,
    DecisionProductFacts,
    DecisionResult,
    FactState,
    RiskFinding,
    WinnerStatus,
)
from app.guide.decision.deterministic_ranking import (
    sort_product_candidates,
)
from app.guide.decision.concept_ranking import (
    rank_common_concepts,
)
from app.guide.decision.facet_ranking import rank_soft_facets
from app.guide.decision.relative_comparison import (
    compare_relative_candidate,
)
from app.guide.decision.ports import DecisionFactPort
from app.guide.intent.contracts import (
    BudgetConstraint,
    CategoryConstraint,
    ConceptConstraint,
    EfficacyConstraint,
    ExclusionConstraint,
    FacetConstraint,
    InclusionConstraint,
    RelativeRequirement,
    SkinConstraint,
    TaskConstraint,
)
from app.guide.retrieval.category_taxonomy import (
    canonical_categories_for,
)
from app.guide.retrieval.contracts import RetrievalResult
from app.guide.retrieval.ingredient_entities import (
    ingredient_entities_match,
)
from app.guide.retrieval.selection_parent_concept_reader import (
    SelectionParentConceptReader,
)
from app.guide.understanding.contracts import EfficacyTarget, SkinTarget

SkinMatch = Literal[
    "matched",
    "unknown",
    "mismatch",
    "not_applicable",
]
EfficacyMatch = Literal[
    "matched",
    "unknown",
    "mismatch",
    "not_applicable",
]

_GENERIC_SKIN_MARKERS = (
    "多种肤质",
    "全肤质",
    "任何肤质",
    "通用",
)
_EXPLICIT_SKIN_MARKERS = {
    SkinTarget.OILY_SENSITIVE: ("油敏",),
    SkinTarget.OILY: ("油皮", "油性"),
    SkinTarget.DRY: ("干皮", "干性"),
    SkinTarget.COMBINATION: ("混合", "混油", "混干"),
    SkinTarget.SENSITIVE: ("敏感肌", "敏感性肤质", "敏皮"),
    SkinTarget.NORMAL: ("中性",),
}
_EFFICACY_MARKERS = {
    EfficacyTarget.HYDRATION: ("保湿", "补水"),
    EfficacyTarget.SOOTHING: ("舒缓",),
    EfficacyTarget.REPAIR: ("修护", "修复"),
    EfficacyTarget.ANTI_AGING: ("抗老", "抗皱", "淡纹"),
    EfficacyTarget.BRIGHTENING: ("提亮", "美白"),
    EfficacyTarget.OIL_CONTROL: ("控油",),
    EfficacyTarget.ACNE_CARE: ("祛痘", "痘肌"),
}


def decide_recommendation(
    facts: DecisionFactPort,
    retrieval: RetrievalResult,
    *,
    constraints: list[TaskConstraint],
    safety_sensitive: bool = False,
    concept_reader: SelectionParentConceptReader | None = None,
    relative_requirement: RelativeRequirement | None = None,
    baseline_product_id: int | None = None,
) -> DecisionResult:
    budget = next(
        (
            item
            for item in constraints
            if isinstance(item, BudgetConstraint)
        ),
        None,
    )
    category = next(
        (
            item
            for item in constraints
            if isinstance(item, CategoryConstraint)
        ),
        None,
    )
    skin = next(
        (
            item
            for item in constraints
            if isinstance(item, SkinConstraint)
        ),
        None,
    )
    efficacy = next(
        (
            item
            for item in constraints
            if isinstance(item, EfficacyConstraint)
        ),
        None,
    )
    exclusions = [
        item
        for item in constraints
        if isinstance(item, ExclusionConstraint)
    ]
    inclusions = [
        item
        for item in constraints
        if isinstance(item, InclusionConstraint)
    ]
    facets = tuple(
        item
        for item in constraints
        if isinstance(item, FacetConstraint)
    )
    concepts = tuple(
        item
        for item in constraints
        if isinstance(item, ConceptConstraint)
    )
    if concepts and concept_reader is None:
        raise ValueError(
            "concept constraints require parent concept reader"
        )
    if (relative_requirement is None) != (
        baseline_product_id is None
    ):
        raise ValueError(
            "relative requirement and baseline product must be paired"
        )
    baseline_product = None
    if (
        relative_requirement is not None
        and baseline_product_id is not None
    ):
        baseline_product = facts.get_decision_facts(
            baseline_product_id
        )
        if baseline_product.product_id != baseline_product_id:
            raise ValueError("baseline decision facts product mismatch")
    if category is None:
        raise ValueError("decision requires category constraint")
    allowed_categories = canonical_categories_for(category.value)

    rows: list[dict[str, object]] = []
    evaluations: list[CandidateEvaluation] = []
    risk_findings: list[RiskFinding] = []
    concept_source_refs: set[str] = set()
    relative_source_refs: set[str] = set()
    relative_comparisons = []

    for candidate in retrieval.candidates:
        product = facts.get_decision_facts(candidate.product_id)
        if product.product_id != candidate.product_id:
            raise ValueError("decision facts product_id mismatch")

        if candidate.canonical_category_state != "known":
            evaluations.append(
                _evaluation(
                    product,
                    disposition="excluded_category_unknown",
                    skin_match="not_applicable",
                    efficacy_match="not_applicable",
                    matched_efficacies=[],
                    reasons=[
                        "canonical_category_state="
                        f"{candidate.canonical_category_state}"
                    ],
                )
            )
            if candidate.canonical_category_state == "conflict":
                risk_findings.append(
                    RiskFinding(
                        kind="canonical_fact_conflict",
                        product_id=product.product_id,
                        detail="品类事实冲突，已按 fail-closed 排除",
                    )
                )
            continue

        if candidate.canonical_category not in allowed_categories:
            evaluations.append(
                _evaluation(
                    product,
                    disposition="excluded_category_mismatch",
                    skin_match="not_applicable",
                    efficacy_match="not_applicable",
                    matched_efficacies=[],
                    reasons=["canonical_category_mismatch"],
                )
            )
            continue

        if (
            product.price_state is not FactState.KNOWN
            or product.price is None
        ):
            evaluations.append(
                _evaluation(
                    product,
                    disposition="excluded_price_unknown",
                    skin_match="not_applicable",
                    efficacy_match="not_applicable",
                    matched_efficacies=[],
                    reasons=[f"price_state={product.price_state.value}"],
                )
            )
            if product.price_state is FactState.CONFLICT:
                risk_findings.append(
                    RiskFinding(
                        kind="canonical_fact_conflict",
                        product_id=product.product_id,
                        detail="价格事实冲突，已按 fail-closed 排除",
                    )
                )
            continue

        if _outside_budget(product, budget):
            evaluations.append(
                _evaluation(
                    product,
                    disposition="excluded_budget",
                    skin_match="not_applicable",
                    efficacy_match="not_applicable",
                    matched_efficacies=[],
                    reasons=["outside_budget"],
                )
            )
            continue

        efficacy_match, matched_efficacies = _efficacy_match(
            product,
            efficacy,
        )
        if efficacy_match == "mismatch":
            evaluations.append(
                _evaluation(
                    product,
                    disposition="excluded_efficacy_mismatch",
                    skin_match="not_applicable",
                    efficacy_match="mismatch",
                    matched_efficacies=[],
                    reasons=["known_efficacy_mismatch"],
                )
            )
            continue
        if efficacy_match == "unknown":
            evaluations.append(
                _evaluation(
                    product,
                    disposition="excluded_efficacy_unknown",
                    skin_match="not_applicable",
                    efficacy_match="unknown",
                    matched_efficacies=[],
                    reasons=["efficacy_evidence_unknown"],
                )
            )
            is_conflict = product.efficacy_state is FactState.CONFLICT
            risk_findings.append(
                RiskFinding(
                    kind=(
                        "canonical_fact_conflict"
                        if is_conflict
                        else "efficacy_evidence_unknown"
                    ),
                    product_id=product.product_id,
                    detail=(
                        "修护功效事实冲突，已按 fail-closed 排除"
                        if is_conflict
                        else "修护功效缺少可用审核证据"
                    ),
                )
            )
            continue

        (
            exclusion_disposition,
            exclusion_conflict,
        ) = _exclusion_disposition(
            product,
            exclusions,
        )
        if exclusion_disposition is not None:
            evaluations.append(
                _evaluation(
                    product,
                    disposition=exclusion_disposition,
                    skin_match="not_applicable",
                    efficacy_match=efficacy_match,
                    matched_efficacies=matched_efficacies,
                    reasons=[exclusion_disposition],
                )
            )
            if exclusion_disposition == "excluded_evidence_unknown":
                risk_findings.append(
                    RiskFinding(
                        kind=(
                            "canonical_fact_conflict"
                            if exclusion_conflict
                            else "exclusion_evidence_unknown"
                        ),
                        product_id=product.product_id,
                        detail=(
                            "排除项成分事实冲突，已按 fail-closed 排除"
                            if exclusion_conflict
                            else "缺少排除项不存在的审核证据"
                        ),
                    )
                )
            continue

        if _missing_hard_inclusion(product, inclusions):
            evaluations.append(
                _evaluation(
                    product,
                    disposition="excluded_evidence_unknown",
                    skin_match="not_applicable",
                    efficacy_match=efficacy_match,
                    matched_efficacies=matched_efficacies,
                    reasons=["included_ingredient_evidence_unknown"],
                )
            )
            risk_findings.append(
                RiskFinding(
                    kind="exclusion_evidence_unknown",
                    product_id=product.product_id,
                    detail="缺少必含成分的强事实，已按 fail-closed 排除",
                )
            )
            continue

        skin_match = resolve_skin_match(product, skin)
        if skin_match == "mismatch":
            evaluations.append(
                _evaluation(
                    product,
                    disposition="excluded_skin_mismatch",
                    skin_match="mismatch",
                    efficacy_match=efficacy_match,
                    matched_efficacies=matched_efficacies,
                    reasons=["known_skin_mismatch"],
                )
            )
            continue
        if skin_match == "unknown":
            risk_findings.append(
                RiskFinding(
                    kind="skin_match_unknown",
                    product_id=product.product_id,
                    detail="肤质数据缺失，未确认是否适合",
                )
            )

        facet_ranking = rank_soft_facets(
            product,
            facets,
            safety_sensitive=safety_sensitive,
        )
        concept_ranking = (
            rank_common_concepts(
                product,
                concepts,
                reader=concept_reader,
                safety_sensitive=safety_sensitive,
            )
            if concepts and concept_reader is not None
            else None
        )
        if concept_ranking is not None:
            concept_source_refs.update(
                reference
                for slot in concept_ranking.slots
                if slot.match_status != "unknown"
                for reference in slot.source_refs
            )
        relative_result = (
            compare_relative_candidate(
                candidate=product,
                baseline=baseline_product,
                field_key=relative_requirement.field_key,
                concept_id=relative_requirement.concept_id,
                direction=relative_requirement.direction,
                reader=concept_reader,
            )
            if (
                relative_requirement is not None
                and baseline_product is not None
            )
            else None
        )
        if (
            relative_result is not None
            and relative_result.status == "better"
        ):
            relative_source_refs.update(
                relative_result.source_refs
            )
        if relative_result is not None:
            relative_comparisons.append(relative_result)
        rows.append({
            "id": product.product_id,
            "skin_rank": 1 if skin_match == "unknown" else 0,
            "facet_mismatch_count": (
                facet_ranking.mismatch_count
                + (
                    concept_ranking.mismatch_count
                    if concept_ranking is not None
                    else 0
                )
            ),
            "facet_unknown_count": (
                facet_ranking.unknown_count
                + (
                    concept_ranking.unknown_count
                    if concept_ranking is not None
                    else 0
                )
            ),
            "weighted_match_score": (
                facet_ranking.weighted_match_score
                + (
                    concept_ranking.weighted_match_score
                    if concept_ranking is not None
                    else 0
                )
            ),
            "relative_rank": (
                {
                    "better": 0,
                    "not_better": 1,
                    "evidence_gap": 2,
                }[relative_result.status]
                if relative_result is not None
                else 0
            ),
            "price": product.price,
            "price_order_key": _price_order_key(
                product.price,
                budget,
            ),
        })
        evaluations.append(
            _evaluation(
                product,
                disposition="eligible",
                skin_match=skin_match,
                efficacy_match=efficacy_match,
                matched_efficacies=matched_efficacies,
                reasons=["hard_constraints_passed"],
            )
        )

    if facets or concepts or relative_requirement is not None:
        ordered = sort_product_candidates(
            rows,
            business_key=lambda row: (
                row["skin_rank"],
                row["facet_mismatch_count"],
                row["relative_rank"],
                row["weighted_match_score"],
                row["facet_unknown_count"],
                row["price_order_key"],
            ),
            directions=(
                "asc",
                "asc",
                "asc",
                "desc",
                "asc",
                "asc",
            ),
            business_key_names=(
                "skin_rank",
                "facet_mismatch_count",
                "relative_rank",
                "weighted_match_score",
                "facet_unknown_count",
                (
                    "budget_proximity"
                    if budget is not None
                    and budget.maximum is not None
                    else "price"
                ),
            ),
            chain="slice1_recommendation",
        )
    else:
        ordered = sort_product_candidates(
            rows,
            business_key=lambda row: (
                row["skin_rank"],
                row["price_order_key"],
            ),
            directions=("asc", "asc"),
            business_key_names=(
                "skin_rank",
                (
                    "budget_proximity"
                    if budget is not None
                    and budget.maximum is not None
                    else "price"
                ),
            ),
            chain="slice1_recommendation",
        )
    ordered_ids = [int(row["id"]) for row in ordered.items]
    winner_status, winner_id, tie_reason = _winner(
        ordered,
        skin_required=skin is not None,
    )

    evidence_refs = [f"category={category.value.value}"]
    if budget is not None and budget.minimum is not None:
        evidence_refs.append(f"budget_min>={budget.minimum}")
    if budget is not None and budget.maximum is not None:
        evidence_refs.append(f"budget_max<={budget.maximum}")
    if skin is not None:
        evidence_refs.append(f"skin={skin.value.value}")
    evidence_refs.extend(
        f"exclude={item.value}"
        for item in exclusions
    )
    evidence_refs.extend(
        f"include={item.value}"
        for item in inclusions
    )
    if efficacy is not None:
        evidence_refs.append(f"efficacy={efficacy.value.value}")
    evidence_refs.extend(
        f"facet={item.field_key}:{item.value}"
        for item in facets
    )
    evidence_refs.extend(
        (
            f"concept={item.field_key}:"
            f"{item.concept_id}:{item.polarity}"
        )
        for item in concepts
    )
    evidence_refs.extend(sorted(concept_source_refs))
    evidence_refs.extend(sorted(relative_source_refs))
    if relative_requirement is not None:
        evidence_refs.append(
            "relative="
            f"{relative_requirement.field_key}:"
            f"{relative_requirement.direction}"
        )

    dimensions: list[str] = []
    if skin is not None:
        dimensions.append("skin_match")
    if efficacy is not None:
        dimensions.append("efficacy_match")
    dimensions.extend(
        f"facet:{item.field_key}"
        for item in facets
    )
    dimensions.extend(
        f"concept:{item.field_key}"
        for item in concepts
    )
    if relative_requirement is not None:
        dimensions.append(
            "relative:"
            f"{relative_requirement.field_key}:"
            f"{relative_requirement.direction}"
        )
    dimensions.append("price")

    return DecisionResult(
        ordered_product_ids=ordered_ids,
        winner_status=winner_status,
        winner_product_id=winner_id,
        evaluations=evaluations,
        comparison_dimensions=dimensions,
        risk_findings=risk_findings,
        evidence_refs=evidence_refs,
        relative_comparisons=relative_comparisons,
        tie_reason=tie_reason,
    )


def _outside_budget(
    product: DecisionProductFacts,
    budget: BudgetConstraint | None,
) -> bool:
    if budget is None:
        return False
    assert product.price is not None
    return (
        budget.minimum is not None
        and product.price < budget.minimum
    ) or (
        budget.maximum is not None
        and product.price > budget.maximum
    )


def _price_order_key(
    price: Decimal,
    budget: BudgetConstraint | None,
) -> Decimal:
    if budget is not None and budget.maximum is not None:
        return budget.maximum - price
    return price


def _exclusion_disposition(
    product: DecisionProductFacts,
    exclusions: list[ExclusionConstraint],
) -> tuple[
    Literal[
        "excluded_exclusion_match",
        "excluded_evidence_unknown",
    ]
    | None,
    bool,
]:
    for exclusion in exclusions:
        present = product.ingredients_present or ()
        absent = product.verified_absences or ()
        if (
            product.ingredients_present_state is FactState.KNOWN
            and any(
                ingredient_entities_match(exclusion.value, value)
                for value in present
            )
        ):
            return "excluded_exclusion_match", False
        if (
            product.ingredients_present_state is FactState.CONFLICT
            or product.verified_absences_state is FactState.CONFLICT
        ):
            return "excluded_evidence_unknown", True
        if (
            product.verified_absences_state is FactState.KNOWN
            and any(
                ingredient_entities_match(exclusion.value, value)
                for value in absent
            )
        ):
            continue
        return "excluded_evidence_unknown", False
    return None, False


def _missing_hard_inclusion(
    product: DecisionProductFacts,
    inclusions: list[InclusionConstraint],
) -> bool:
    for inclusion in inclusions:
        term = inclusion.value.casefold()
        if not any(
            fact.field_key == inclusion.field_key
            and fact.subject_scope == "exact_product"
            and fact.variant_scope is None
            and "hard_filter" in fact.capabilities
            and term in fact.normalized_value.casefold()
            for fact in product.selection_facts
        ):
            return True
    return False


def _efficacy_match(
    product: DecisionProductFacts,
    constraint: EfficacyConstraint | None,
) -> tuple[EfficacyMatch, list[str]]:
    if constraint is None:
        return "not_applicable", []
    if (
        product.efficacy_state is not FactState.KNOWN
        or product.efficacy is None
    ):
        return "unknown", []
    markers = _EFFICACY_MARKERS[constraint.value]
    matches = [
        value
        for value in product.efficacy
        if any(marker in value for marker in markers)
    ]
    if not matches:
        return "mismatch", []
    return "matched", matches


def resolve_skin_match(
    product: DecisionProductFacts,
    constraint: SkinConstraint | None,
) -> SkinMatch:
    if constraint is None:
        return "not_applicable"
    if (
        product.suitable_skin_state is not FactState.KNOWN
        or product.suitable_skin is None
    ):
        return "unknown"

    combined = " ".join(product.suitable_skin)
    if constraint.value in {
        SkinTarget.SENSITIVE,
        SkinTarget.OILY_SENSITIVE,
    } and any(
        value in combined
        for value in (
            "敏感肌除外",
            "敏感肌不适用",
            "不适合敏感肌",
        )
    ):
        return "mismatch"

    target_markers = _EXPLICIT_SKIN_MARKERS[constraint.value]
    if constraint.value is SkinTarget.OILY_SENSITIVE:
        if "油敏" in combined or (
            any(value in combined for value in ("油皮", "油性"))
            and any(
                value in combined
                for value in ("敏感肌", "敏感性肤质", "敏皮")
            )
        ):
            return "matched"
    elif any(marker in combined for marker in target_markers):
        return "matched"

    if any(marker in combined for marker in _GENERIC_SKIN_MARKERS):
        return "unknown"

    other_markers = {
        marker
        for target, markers in _EXPLICIT_SKIN_MARKERS.items()
        if target is not constraint.value
        for marker in markers
    }
    if any(marker in combined for marker in other_markers):
        return "mismatch"
    return "unknown"


def _evaluation(
    product: DecisionProductFacts,
    *,
    disposition: Literal[
        "eligible",
        "excluded_category_mismatch",
        "excluded_category_unknown",
        "excluded_price_unknown",
        "excluded_budget",
        "excluded_efficacy_mismatch",
        "excluded_efficacy_unknown",
        "excluded_skin_mismatch",
        "excluded_exclusion_match",
        "excluded_evidence_unknown",
    ],
    skin_match: SkinMatch,
    efficacy_match: EfficacyMatch,
    matched_efficacies: list[str],
    reasons: list[str],
) -> CandidateEvaluation:
    return CandidateEvaluation(
        product_id=product.product_id,
        disposition=disposition,
        price=product.price,
        skin_match=skin_match,
        efficacy_match=efficacy_match,
        matched_efficacies=matched_efficacies,
        reasons=reasons,
    )


def _winner(
    ordered,
    *,
    skin_required: bool,
) -> tuple[WinnerStatus, int | None, str | None]:
    if not ordered.items:
        return WinnerStatus.NO_CANDIDATE, None, None
    top = ordered.items[0]
    top_id = int(top["id"])
    if skin_required and top["skin_rank"] == 1:
        return WinnerStatus.INSUFFICIENT_FOR_WINNER, None, None
    top_tie = ordered.tie_reason_by_id.get(top_id)
    if top_tie is not None:
        return (
            WinnerStatus.TIED_BY_BUSINESS_EVIDENCE,
            None,
            json.dumps(
                top_tie,
                ensure_ascii=False,
                sort_keys=True,
            ),
        )
    return WinnerStatus.SELECTED, top_id, None
