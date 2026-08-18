from __future__ import annotations

import re
from collections import defaultdict
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.guide.retrieval.product_evidence_assets import ProductEvidenceBlock
from app.guide.retrieval.product_evidence_reader import ProductEvidenceReader


_NON_TEXT = re.compile(r"[^0-9a-z\u3400-\u9fff]+", re.IGNORECASE)
_ASCII_WORD = re.compile(r"[0-9a-z]+", re.IGNORECASE)
_CJK = re.compile(r"[\u3400-\u9fff]")
_SAFETY_CAVEAT = (
    "现有相关内容属于商家安全宣称，未经强证据核实，"
    "不能作为安全保证或硬筛依据。"
)
_EVIDENCE_LIMIT = re.compile(
    r"(?:不支持|未(?:显示|披露|给出|说明)|"
    r"无法(?:确认|判断|可靠)|不能据此(?:判断|确认))"
)
_PROVENANCE_LANGUAGE = re.compile(
    r"(?:商家|品牌)"
    r"(?:(?:有没有|有没|是否)?"
    r"(?:说(?:过|的)?|宣称|宣传|陈述|引用))"
)
_RELATION_DIMENSION_LABELS = {
    "net_content": "容量规格",
}


class _StrictFrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class EvidenceQuery(_StrictFrozenModel):
    product_ids: tuple[int, ...] = Field(min_length=1, max_length=4)
    raw_question: str = Field(min_length=1, max_length=4000)
    question_meaning: str = Field(min_length=1, max_length=256)
    safety_sensitive: bool
    product_mention_spans: tuple[tuple[int, int], ...] = Field(
        default_factory=tuple,
        max_length=4,
    )
    product_identity_names: tuple[str, ...] = Field(
        default_factory=tuple,
        max_length=4,
    )

    @field_validator(
        "product_ids",
        "product_mention_spans",
        "product_identity_names",
        mode="before",
    )
    @classmethod
    def freeze_query_sequences(cls, value: object) -> object:
        if isinstance(value, list):
            return tuple(
                tuple(item) if isinstance(item, list) else item
                for item in value
            )
        return value

    @model_validator(mode="after")
    def validate_query(self) -> Self:
        if (
            any(
                not isinstance(product_id, int)
                or isinstance(product_id, bool)
                or product_id <= 0
                for product_id in self.product_ids
            )
            or len(self.product_ids) != len(set(self.product_ids))
        ):
            raise ValueError("evidence query product IDs are invalid")
        if not self.raw_question.strip() or not self.question_meaning.strip():
            raise ValueError("evidence query text must be nonempty")
        if self.product_identity_names:
            if (
                len(self.product_identity_names) != len(self.product_ids)
                or any(
                    not name.strip() or len(name) > 160
                    for name in self.product_identity_names
                )
            ):
                raise ValueError(
                    "product identity names must align with product IDs"
                )
        ordered_spans = sorted(self.product_mention_spans)
        for index, span in enumerate(ordered_spans):
            if (
                len(span) != 2
                or any(
                    not isinstance(value, int)
                    or isinstance(value, bool)
                    for value in span
                )
                or span[0] < 0
                or span[1] <= span[0]
                or span[1] > len(self.raw_question)
                or (
                    index > 0
                    and ordered_spans[index - 1][1] > span[0]
                )
            ):
                raise ValueError(
                    "product mention spans are invalid"
                )
        return self


class EvidenceSelection(_StrictFrozenModel):
    evidence: ProductEvidenceBlock
    score: float = Field(gt=0.0, allow_inf_nan=False)
    reasons: tuple[str, ...] = Field(min_length=1)

    @field_validator("reasons", mode="before")
    @classmethod
    def freeze_reasons(cls, value: object) -> object:
        if isinstance(value, list):
            return tuple(value)
        return value


class EvidencePacket(_StrictFrozenModel):
    query: EvidenceQuery
    selected: tuple[EvidenceSelection, ...]
    safety_caveats: tuple[str, ...]
    missing_aspects: tuple[str, ...]
    ambiguity_reasons: tuple[str, ...] = ()

    @field_validator(
        "selected",
        "safety_caveats",
        "missing_aspects",
        "ambiguity_reasons",
        mode="before",
    )
    @classmethod
    def freeze_packet_sequences(cls, value: object) -> object:
        if isinstance(value, list):
            return tuple(value)
        return value


class ProductEvidenceRetriever:
    def __init__(
        self,
        reader: ProductEvidenceReader,
        *,
        per_product_limit: int = 5,
        total_limit: int = 8,
    ) -> None:
        if not isinstance(reader, ProductEvidenceReader):
            raise TypeError("reader must be ProductEvidenceReader")
        if (
            not isinstance(per_product_limit, int)
            or isinstance(per_product_limit, bool)
            or per_product_limit <= 0
            or not isinstance(total_limit, int)
            or isinstance(total_limit, bool)
            or total_limit <= 0
            or total_limit < per_product_limit
        ):
            raise ValueError("evidence limits are invalid")
        self._reader = reader
        self._per_product_limit = per_product_limit
        self._total_limit = total_limit

    def retrieve(self, query: EvidenceQuery) -> EvidencePacket:
        if not isinstance(query, EvidenceQuery):
            raise TypeError("query must be EvidenceQuery")
        scored_by_product: dict[int, list[EvidenceSelection]] = defaultdict(list)
        answerable_by_product: dict[
            int,
            tuple[ProductEvidenceBlock, ...],
        ] = {}
        for product_id in query.product_ids:
            answerable = self._reader.read_answerable(
                product_id=product_id
            )
            answerable_by_product[product_id] = answerable
            for block in answerable:
                score, reasons = _score_block(query, block)
                if score <= 0:
                    continue
                scored_by_product[product_id].append(
                    EvidenceSelection(
                        evidence=block,
                        score=score,
                        reasons=tuple(reasons),
                    )
                )
        candidates: list[EvidenceSelection] = []
        ambiguity_reasons: list[str] = []
        for product_id in query.product_ids:
            ordered = sorted(
                scored_by_product.get(product_id, ()),
                key=lambda item: (-item.score, item.evidence.evidence_id),
            )
            ordered, product_ambiguities = (
                _include_unresolved_variant_relations(
                    query,
                    ordered,
                    answerable_by_product[product_id],
                )
            )
            ambiguity_reasons.extend(product_ambiguities)
            candidates.extend(
                _deduplicate(ordered)[: self._per_product_limit]
            )
        candidates.sort(
            key=lambda item: (
                -item.score,
                query.product_ids.index(item.evidence.product_id),
                item.evidence.evidence_id,
            )
        )
        selected = tuple(candidates[: self._total_limit])
        safety_caveats: tuple[str, ...] = ()
        if query.safety_sensitive:
            if any(
                item.evidence.management_label == "safety_transcript"
                for item in selected
            ):
                safety_caveats = (_SAFETY_CAVEAT,)
            else:
                safety_caveats = (
                    "当前商品证据不足以确认该安全问题，不能据此作安全保证。",
                )
        missing_aspects = (
            ()
            if selected
            else ("未找到与当前问题直接相关的已审核商品证据。",)
        )
        return EvidencePacket(
            query=query,
            selected=selected,
            safety_caveats=safety_caveats,
            missing_aspects=missing_aspects,
            ambiguity_reasons=tuple(dict.fromkeys(ambiguity_reasons)),
        )


def _score_block(
    query: EvidenceQuery,
    block: ProductEvidenceBlock,
) -> tuple[float, list[str]]:
    product_mentions = _product_mention_texts(query)
    searchable_raw_question = _without_provenance_language(
        _mask_product_mentions(query)
    )
    searchable_meaning = _without_provenance_language(
        _remove_product_mentions(
            query.question_meaning,
            product_mentions,
        )
    )
    query_text = (
        f"{searchable_raw_question} {searchable_meaning}"
    )
    raw_features = _features(searchable_raw_question)
    meaning_features = _features(searchable_meaning)
    if query.product_identity_names:
        identity_features = set().union(
            *(
                _features(name)
                for name in query.product_identity_names
            )
        )
        meaning_features.difference_update(identity_features)
    query_feature_sets = (raw_features, meaning_features)
    query_features = set().union(*query_feature_sets)
    primary_parts = [
        block.exact_text,
        block.plain_meaning,
        *block.free_descriptors,
        *(
            value
            for relation in block.relations
            for value in (
                relation.subject,
                relation.predicate,
                relation.object,
            )
        ),
    ]
    qualifier_parts = [
        *(
            [str(block.qualifiers.sample_size)]
            if block.qualifiers.sample_size is not None
            else []
        ),
        *(
            value
            for value in (
                block.qualifiers.population,
                block.qualifiers.method,
                block.qualifiers.baseline,
                block.qualifiers.duration,
                block.qualifiers.disclaimer,
            )
            if value is not None
        ),
        *block.qualifiers.footnotes,
    ]
    primary_text = " ".join(primary_parts)
    qualifier_text = " ".join(qualifier_parts)
    primary_features = _features(primary_text)
    qualifier_features = _features(qualifier_text)
    primary_overlap = query_features & primary_features
    qualifier_overlap = query_features & qualifier_features
    variant_coverage = _confirmed_variant_coverage(
        block,
        product_mentions=product_mentions,
    )
    safety_transcript_candidate = (
        query.safety_sensitive
        and block.management_label == "safety_transcript"
    )
    if (
        not primary_overlap
        and not qualifier_overlap
        and variant_coverage <= 0
        and not safety_transcript_candidate
    ):
        return 0.0, []
    primary_union = query_features | primary_features
    score = (
        4.0
        * len(primary_overlap)
        / max(1, len(primary_union))
    )
    reasons = (
        ["semantic_feature_overlap"]
        if primary_overlap
        else ["safety_transcript_nomination"]
    )
    raw_coverage = (
        len(raw_features & primary_features) / len(raw_features)
        if raw_features
        else 0.0
    )
    meaning_coverage = (
        len(meaning_features & primary_features)
        / len(meaning_features)
        if meaning_features
        else 0.0
    )
    if raw_coverage > 0:
        score += raw_coverage
        reasons.append("raw_question_coverage")
    if meaning_coverage > 0:
        score += 3.0 * meaning_coverage
        reasons.append("question_meaning_coverage")
    if qualifier_overlap:
        qualifier_union = query_features | qualifier_features
        qualifier_coverage = max(
            (
                len(features & qualifier_features) / len(features)
                for features in query_feature_sets
                if features
            ),
            default=0.0,
        )
        score += (
            0.5
            * len(qualifier_overlap)
            / max(1, len(qualifier_union))
        )
        score += 0.75 * qualifier_coverage
        reasons.append("qualifier_feature_overlap")

    compact_query = _compact(query_text)
    compact_evidence = _compact(primary_text)
    descriptor_bonus = 0.0
    descriptor_reason: str | None = None
    for descriptor in block.free_descriptors:
        compact_descriptor = _compact(descriptor)
        if (
            len(compact_descriptor) >= 2
            and compact_descriptor in compact_query
        ):
            candidate_bonus = 0.25
            candidate_reason = "free_descriptor_match"
        else:
            descriptor_features = _features(descriptor)
            feature_coverage = (
                len(descriptor_features & query_features)
                / len(descriptor_features)
                if descriptor_features
                else 0.0
            )
            feature_bonus = (
                min(0.75, 0.35 + 0.4 * feature_coverage)
                if feature_coverage > 0
                else 0.0
            )
            descriptor_unigrams = _cjk_unigrams(descriptor)
            query_unigrams = _cjk_unigrams(query_text)
            unigram_bonus = (
                min(
                    0.20,
                    1.5
                    * len(descriptor_unigrams & query_unigrams)
                    / len(descriptor_unigrams),
                )
                if descriptor_unigrams
                else 0.0
            )
            if feature_bonus >= unigram_bonus:
                candidate_bonus = feature_bonus
                candidate_reason = (
                    "free_descriptor_feature_overlap"
                )
            else:
                candidate_bonus = unigram_bonus
                candidate_reason = (
                    "free_descriptor_unigram_overlap"
                )
        if candidate_bonus > descriptor_bonus:
            descriptor_bonus = candidate_bonus
            descriptor_reason = candidate_reason
    if descriptor_reason is not None:
        score += min(descriptor_bonus, 0.75)
        reasons.append(descriptor_reason)
    if (
        compact_query
        and len(compact_query) >= 4
        and compact_query in compact_evidence
    ):
        score += 3.0
        reasons.append("exact_query_match")
    if block.subject_scope == "exact_variant":
        score += 0.3
        reasons.append("exact_variant_scope")
    elif block.subject_scope == "exact_product":
        score += 0.2
        reasons.append("exact_product_scope")
    elif block.subject_scope == "brand":
        score -= 0.4
        reasons.append("brand_scope_penalty")
    if variant_coverage > 0:
        score += min(2.0 * variant_coverage, 1.5)
        reasons.append("confirmed_variant_scope_match")
    if _EVIDENCE_LIMIT.search(block.plain_meaning):
        score -= 0.75
        reasons.append("explicit_evidence_limit_penalty")
    if query.safety_sensitive:
        if block.management_label == "safety_transcript":
            score += 4.0
            reasons.append("safety_transcript_priority")
        elif "safety_guarantee" in block.forbidden_uses:
            score -= 0.2
    return max(score, 0.0), list(dict.fromkeys(reasons))


def _include_unresolved_variant_relations(
    query: EvidenceQuery,
    ordered: list[EvidenceSelection],
    answerable: tuple[ProductEvidenceBlock, ...],
) -> tuple[list[EvidenceSelection], tuple[str, ...]]:
    strong_by_dimension: dict[
        str,
        list[tuple[ProductEvidenceBlock, str, str]],
    ] = defaultdict(list)
    for block in answerable:
        if (
            block.subject_scope != "exact_variant"
            or "hard_filter" not in block.allowed_uses
        ):
            continue
        for relation in block.relations:
            dimension = _relation_dimension(relation.predicate)
            strong_by_dimension[dimension].append(
                (block, relation.subject, relation.object)
            )

    by_id = {
        selection.evidence.evidence_id: selection
        for selection in ordered
    }
    ambiguity_reasons: list[str] = []
    for dimension in sorted(strong_by_dimension):
        rows = strong_by_dimension[dimension]
        if len({block.evidence_id for block, _, _ in rows}) < 2:
            continue
        distinct_objects = {
            _compact(object_value)
            for _, _, object_value in rows
            if _compact(object_value)
        }
        if len(distinct_objects) < 2:
            continue
        anchors = [
            by_id[block.evidence_id]
            for block, _, _ in rows
            if block.evidence_id in by_id
        ]
        if (
            not anchors
            or not _relation_dimension_is_relevant(query, anchors)
            or _query_specifies_variant_relation(query, rows)
        ):
            continue
        anchor = sorted(
            anchors,
            key=lambda item: (
                -item.score,
                item.evidence.evidence_id,
            ),
        )[0]
        row_by_evidence: dict[
            str,
            tuple[ProductEvidenceBlock, str],
        ] = {}
        for block, _, object_value in rows:
            row_by_evidence.setdefault(
                block.evidence_id,
                (block, object_value),
            )
        related_rows = sorted(
            row_by_evidence.values(),
            key=lambda item: (
                item[0].evidence_id != anchor.evidence.evidence_id,
                item[0].evidence_id,
            ),
        )
        for index, (block, _) in enumerate(related_rows, start=1):
            if block.evidence_id in by_id:
                continue
            selection = EvidenceSelection(
                evidence=block,
                score=max(anchor.score - 0.001 * index, 0.000001),
                reasons=("related_variant_dimension",),
            )
            ordered.append(selection)
            by_id[block.evidence_id] = selection
        label = _RELATION_DIMENSION_LABELS.get(
            dimension,
            dimension.replace("_", " "),
        )
        details = "；".join(
            f"{block.variant_scope or '未命名变体'}为{object_value}"
            for block, object_value in related_rows
        )
        ambiguity_reasons.append(
            f"已审核证据包含多个{label}变体：{details}。"
            "当前问题未限定具体规格，请核对所选或收到的版本。"
        )
    ordered.sort(
        key=lambda item: (-item.score, item.evidence.evidence_id)
    )
    return ordered, tuple(ambiguity_reasons)


def _relation_dimension(predicate: str) -> str:
    parts = [
        part
        for part in predicate.casefold().split("_")
        if part
    ]
    return "_".join(parts[-2:]) if len(parts) >= 2 else predicate.casefold()


def _query_specifies_variant_relation(
    query: EvidenceQuery,
    rows: list[tuple[ProductEvidenceBlock, str, str]],
) -> bool:
    compact_query = _compact(
        f"{query.raw_question} {query.question_meaning}"
    )
    identity_names = {
        _compact(name)
        for name in query.product_identity_names
    }
    for _, subject, object_value in rows:
        compact_object = _compact(object_value)
        if (
            len(compact_object) >= 2
            and compact_object in compact_query
        ):
            return True
        compact_subject = _compact(subject)
        if (
            len(compact_subject) >= 2
            and compact_subject in compact_query
            and compact_subject not in identity_names
        ):
            return True
    return False


def _relation_dimension_is_relevant(
    query: EvidenceQuery,
    anchors: list[EvidenceSelection],
) -> bool:
    query_features = (
        _features(_mask_product_mentions(query))
        | _features(query.question_meaning)
    )
    if query.product_identity_names:
        identity_features = set().union(
            *(
                _features(name)
                for name in query.product_identity_names
            )
        )
        query_features.difference_update(identity_features)
    return any(
        query_features & _features(anchor.evidence.plain_meaning)
        for anchor in anchors
    )


def _features(value: str) -> set[str]:
    compact = _compact(value)
    features = set(_ASCII_WORD.findall(value.casefold()))
    cjk = "".join(character for character in compact if _CJK.fullmatch(character))
    features.update(cjk[index : index + 2] for index in range(len(cjk) - 1))
    features.update(cjk[index : index + 3] for index in range(len(cjk) - 2))
    return {feature for feature in features if feature}


def _compact(value: str) -> str:
    return _NON_TEXT.sub("", value.casefold())


def _cjk_unigrams(value: str) -> set[str]:
    return {
        character
        for character in _compact(value)
        if _CJK.fullmatch(character)
    }


def _mask_product_mentions(query: EvidenceQuery) -> str:
    if not query.product_mention_spans:
        return query.raw_question
    characters = list(query.raw_question)
    for start, end in query.product_mention_spans:
        characters[start:end] = " " * (end - start)
    return "".join(characters)


def _product_mention_texts(
    query: EvidenceQuery,
) -> tuple[str, ...]:
    return tuple(
        query.raw_question[start:end]
        for start, end in query.product_mention_spans
    )


def _remove_product_mentions(
    value: str,
    product_mentions: tuple[str, ...],
) -> str:
    searchable = value
    for mention in sorted(product_mentions, key=len, reverse=True):
        searchable = searchable.replace(mention, " ")
    return searchable


def _without_provenance_language(value: str) -> str:
    return _PROVENANCE_LANGUAGE.sub(" ", value)


def _confirmed_variant_coverage(
    block: ProductEvidenceBlock,
    *,
    product_mentions: tuple[str, ...],
) -> float:
    if (
        block.subject_scope != "exact_variant"
        or block.variant_scope is None
        or not product_mentions
    ):
        return 0.0
    mention_features = set().union(
        *(_features(value) for value in product_mentions)
    )
    variant_features = _features(block.variant_scope)
    if not variant_features:
        return 0.0
    return (
        len(mention_features & variant_features)
        / len(variant_features)
    )


def _deduplicate(
    selections: list[EvidenceSelection],
) -> list[EvidenceSelection]:
    seen: set[tuple[str, str]] = set()
    result: list[EvidenceSelection] = []
    for selection in selections:
        key = (
            selection.evidence.management_label,
            _compact(selection.evidence.exact_text),
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(selection)
    return result


__all__ = [
    "EvidencePacket",
    "EvidenceQuery",
    "EvidenceSelection",
    "ProductEvidenceRetriever",
]
