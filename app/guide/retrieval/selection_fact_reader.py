from __future__ import annotations

import re

from app.guide.retrieval.category_fact_contracts import (
    AuthorizedCategoryFact,
)
from app.guide.retrieval.category_profiles import CategoryProfile
from app.guide.retrieval.merchant_claim_assets import MerchantClaim
from app.guide.retrieval.product_evidence_assets import (
    ProductEvidenceBlock,
)
from app.guide.retrieval.selection_fact_contracts import (
    SelectionCapability,
    SelectionFact,
    merge_selection_facts,
)


_SELECTION_CAPABILITIES = frozenset(
    {"compare", "soft_rank", "hard_filter", "safety_gate"}
)
_SPECIFICATION = re.compile(
    r"(?<![\d.])(?P<amount>\d+(?:\.\d+)?)\s*"
    r"(?P<unit>ml|毫升|g|克)(?![A-Za-z])",
    re.IGNORECASE,
)
_BUNDLE_MARKER = re.compile(
    r"(?:[x×]\s*\d|[+＋]\s*\d|到手|赠(?:送|品)?|组合|套装)",
    re.IGNORECASE,
)


class SelectionFactReader:
    def __init__(
        self,
        *,
        base,
        claims,
        evidence,
    ) -> None:
        self._base = base
        self._claims = claims
        self._evidence = evidence

    def read(
        self,
        *,
        product_id: int,
        profile: CategoryProfile,
    ) -> tuple[SelectionFact, ...]:
        if (
            not isinstance(product_id, int)
            or isinstance(product_id, bool)
            or product_id <= 0
        ):
            raise TypeError("product_id must be a positive integer")
        if not isinstance(profile, CategoryProfile):
            raise TypeError("profile must be a CategoryProfile")
        base = self._base.read(
            product_id=product_id,
            profile=profile,
        )
        claims = self._claims.read(product_id=product_id)
        evidence = self._evidence.read(product_id=product_id)
        projected_base = self._project_base(
            base,
            product_id=product_id,
        )
        projected_claims = self._project_claims(
            claims,
            profile=profile,
        )
        projected_evidence = self._project_evidence(
            evidence,
            profile=profile,
        )
        existing = (
            *projected_base,
            *projected_claims,
            *projected_evidence,
        )
        inferred_specifications = (
            ()
            if any(fact.field_key == "net_content" for fact in existing)
            else self._project_reviewed_specifications(
                evidence,
                profile=profile,
            )
        )
        return merge_selection_facts(
            (
                *existing,
                *inferred_specifications,
            )
        )

    def _project_base(
        self,
        facts: tuple[AuthorizedCategoryFact, ...],
        *,
        product_id: int,
    ) -> tuple[SelectionFact, ...]:
        projected: list[SelectionFact] = []
        for fact in facts:
            if fact.resolved_state != "known":
                continue
            if isinstance(fact.value, str):
                values = (fact.value,)
            elif isinstance(fact.value, tuple):
                values = fact.value
            else:
                continue
            capabilities = _selection_capabilities(fact.capabilities)
            if not capabilities:
                continue
            for value in values:
                projected.append(
                    SelectionFact(
                        product_id=product_id,
                        category_profile=fact.category_profile,
                        subject_scope="exact_product",
                        variant_scope=None,
                        field_key=fact.field_key,
                        normalized_value=value,
                        rank_strength=(
                            2
                            if "soft_rank" in capabilities
                            else None
                        ),
                        safety_role="ordinary",
                        capabilities=capabilities,
                        source_refs=fact.source_refs,
                        attributions={"verified_fact"},
                    )
                )
        return tuple(projected)

    def _project_claims(
        self,
        claims: tuple[MerchantClaim, ...],
        *,
        profile: CategoryProfile,
    ) -> tuple[SelectionFact, ...]:
        projected: list[SelectionFact] = []
        for claim in claims:
            if claim.category_profile is not profile:
                continue
            capabilities = _selection_capabilities(claim.capabilities)
            if not capabilities:
                continue
            projected.append(
                SelectionFact(
                    product_id=claim.product_id,
                    category_profile=profile,
                    subject_scope="exact_product",
                    variant_scope=None,
                    field_key=claim.field_key,
                    normalized_value=claim.normalized_value,
                    rank_strength=(
                        1
                        if "soft_rank" in capabilities
                        else None
                    ),
                    safety_role=(
                        "merchant_positive_safety"
                        if claim.claim_scope == "safety_transcript"
                        else "ordinary"
                    ),
                    capabilities=capabilities,
                    source_refs=(claim.source_locator,),
                    attributions={"merchant_claim"},
                )
            )
        return tuple(projected)

    def _project_evidence(
        self,
        blocks: tuple[ProductEvidenceBlock, ...],
        *,
        profile: CategoryProfile,
    ) -> tuple[SelectionFact, ...]:
        projected: list[SelectionFact] = []
        for block in blocks:
            review = block.selection_review
            if block.review_status != "accepted" or review is None:
                continue
            for item in review.projections:
                projected.append(
                    SelectionFact(
                        product_id=block.product_id,
                        category_profile=profile,
                        subject_scope=block.subject_scope,
                        variant_scope=block.variant_scope,
                        field_key=item.field_key,
                        normalized_value=item.normalized_value,
                        rank_strength=item.rank_strength,
                        safety_role=item.safety_role,
                        capabilities=item.capabilities,
                        source_refs=(block.evidence_id,),
                        attributions={
                            _evidence_attribution(
                                block,
                                rank_strength=item.rank_strength,
                                safety_role=item.safety_role,
                            )
                        },
                    )
                )
        return tuple(projected)

    def _project_reviewed_specifications(
        self,
        blocks: tuple[ProductEvidenceBlock, ...],
        *,
        profile: CategoryProfile,
    ) -> tuple[SelectionFact, ...]:
        projected = []
        for block in blocks:
            specification = _reviewed_card_specification(block)
            if specification is not None:
                projected.append(
                    SelectionFact(
                        product_id=block.product_id,
                        category_profile=profile,
                        subject_scope=block.subject_scope,
                        variant_scope=block.variant_scope,
                        field_key="net_content",
                        normalized_value=specification,
                        rank_strength=None,
                        safety_role="ordinary",
                        capabilities={"compare"},
                        source_refs=(block.evidence_id,),
                        attributions={"verified_fact"},
                    )
                )
        return tuple(projected)


def _reviewed_card_specification(
    block: ProductEvidenceBlock,
) -> str | None:
    if (
        block.subject_scope not in {"exact_product", "exact_variant"}
        or "compare" not in block.allowed_uses
        or block.selection_review is None
        or not block.selection_review.visual_confirmed
        or _BUNDLE_MARKER.search(block.exact_text)
    ):
        return None
    exact_candidates = _specification_values(block.exact_text)
    if len(exact_candidates) != 1:
        return None
    candidate = next(iter(exact_candidates))
    identity_texts = (
        *block.free_descriptors,
        *(
            value
            for relation in block.relations
            for value in (relation.subject, relation.object)
        ),
    )
    if not any(
        candidate in _specification_values(value)
        and not _BUNDLE_MARKER.search(value)
        for value in identity_texts
    ):
        return None
    return candidate


def _specification_values(value: str) -> frozenset[str]:
    normalized = set()
    for match in _SPECIFICATION.finditer(value):
        unit = match.group("unit").casefold()
        normalized_unit = (
            "ml" if unit in {"ml", "毫升"} else "g"
        )
        normalized.add(f"{match.group('amount')}{normalized_unit}")
    return frozenset(normalized)


def _selection_capabilities(
    capabilities,
) -> frozenset[SelectionCapability]:
    return frozenset(
        capability
        for capability in capabilities
        if capability in _SELECTION_CAPABILITIES
    )


def _evidence_attribution(
    block: ProductEvidenceBlock,
    *,
    rank_strength: int | None,
    safety_role: str,
) -> str:
    if block.management_label == "consumer_self_report":
        return "consumer_report"
    if (
        rank_strength == 2
        or safety_role == "verified_warning"
        or block.management_label
        in {"packaging_information", "product_specification"}
    ):
        return "verified_fact"
    return "merchant_claim"


__all__ = ["SelectionFactReader"]
