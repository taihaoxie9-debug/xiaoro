from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Sequence
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.guide.retrieval.product_evidence_assets import ProductEvidenceBlock
from app.guide.retrieval.product_evidence_reader import ProductEvidenceReader


_NON_TEXT = re.compile(r"[^0-9a-z\u3400-\u9fff]+", re.IGNORECASE)
_ASCII_WORD = re.compile(r"[0-9a-z]+", re.IGNORECASE)
_CJK = re.compile(r"[\u3400-\u9fff]")
_SAFETY_CAVEAT = (
    "这段内容是品牌给出的安全说明，"
    "不能把它当作个人安全保证。"
)
_SAFETY_GAP_CAVEAT = (
    "这款没有足以确认该安全问题的信息，"
    "不能把它当作个人安全保证。"
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
_LOW_INFORMATION_CJK = frozenset(
    "这那个款它他她其的是有没否会能吗呢啊呀么怎"
)
_SAFETY_LOW_INFORMATION_CJK = (
    _LOW_INFORMATION_CJK
    | frozenset("安全使用适合可以一定是否风险保证询问")
)
_SOURCE_QUERY_BRIDGES = (
    (re.compile(r"(?:多大|多少毫升|容量)"), "容量规格"),
)


class _StrictFrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class PreparedEvidenceSearch(_StrictFrozenModel):
    source_features: tuple[str, ...] = ()
    meaning_features: tuple[str, ...] = ()
    combined_features: tuple[str, ...] = ()
    query_unigrams: tuple[str, ...] = ()
    product_mention_features: tuple[str, ...] = ()

    @field_validator(
        "source_features",
        "meaning_features",
        "combined_features",
        "query_unigrams",
        "product_mention_features",
        mode="before",
    )
    @classmethod
    def freeze_features(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @model_validator(mode="after")
    def validate_features(self) -> Self:
        for name in (
            "source_features",
            "meaning_features",
            "combined_features",
            "query_unigrams",
            "product_mention_features",
        ):
            values = getattr(self, name)
            if (
                values != tuple(sorted(set(values)))
                or any(not value for value in values)
            ):
                raise ValueError(
                    "prepared evidence features must be sorted and unique"
                )
        if set(self.combined_features) != (
            set(self.source_features) | set(self.meaning_features)
        ):
            raise ValueError(
                "combined evidence features must match source and meaning"
            )
        return self


class EvidenceQuery(_StrictFrozenModel):
    product_ids: tuple[int, ...] = Field(min_length=1, max_length=4)
    search: PreparedEvidenceSearch
    safety_sensitive: bool
    product_identity_names: tuple[str, ...] = Field(
        default_factory=tuple,
        max_length=4,
    )

    @field_validator(
        "product_ids",
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
        return self


def prepare_evidence_search(
    *,
    source_text: str,
    question_meaning: str,
    product_mention_spans: Sequence[tuple[int, int]] = (),
) -> PreparedEvidenceSearch:
    if (
        not isinstance(source_text, str)
        or not source_text.strip()
        or len(source_text) > 4000
        or not isinstance(question_meaning, str)
        or not question_meaning.strip()
        or len(question_meaning) > 256
    ):
        raise ValueError("evidence search text must be nonempty")
    ordered_spans = tuple(sorted(product_mention_spans))
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
            or span[1] > len(source_text)
            or (
                index > 0
                and ordered_spans[index - 1][1] > span[0]
            )
        ):
            raise ValueError("product mention spans are invalid")
    product_mentions = tuple(
        source_text[start:end] for start, end in ordered_spans
    )
    characters = list(source_text)
    for start, end in ordered_spans:
        characters[start:end] = " " * (end - start)
    searchable_source = _without_provenance_language(
        "".join(characters)
    )
    searchable_meaning = _without_provenance_language(
        _remove_product_mentions(
            question_meaning,
            product_mentions,
        )
    )
    source_features = _features(searchable_source)
    for pattern, canonical_text in _SOURCE_QUERY_BRIDGES:
        if pattern.search(searchable_source):
            source_features.update(_features(canonical_text))
    meaning_features = _features(searchable_meaning)
    combined_text = f"{searchable_source} {searchable_meaning}"
    return PreparedEvidenceSearch(
        source_features=tuple(sorted(source_features)),
        meaning_features=tuple(sorted(meaning_features)),
        combined_features=tuple(
            sorted(source_features | meaning_features)
        ),
        query_unigrams=tuple(sorted(_cjk_unigrams(combined_text))),
        product_mention_features=tuple(
            sorted(
                set().union(
                    *(_features(value) for value in product_mentions)
                )
                if product_mentions
                else set()
            )
        ),
    )


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
            product_variant_features = _product_variant_features(
                query,
                product_id=product_id,
            )
            answerable = self._reader.read_answerable(
                product_id=product_id
            )
            answerable_by_product[product_id] = answerable
            for block in answerable:
                score, reasons = _score_block(
                    query,
                    block,
                    product_variant_features=product_variant_features,
                )
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
                    product_variant_features=(
                        _product_variant_features(
                            query,
                            product_id=product_id,
                        )
                    ),
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
                safety_caveats = (_SAFETY_GAP_CAVEAT,)
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
    *,
    product_variant_features: set[str],
) -> tuple[float, list[str]]:
    source_features = set(query.search.source_features)
    meaning_features = set(query.search.meaning_features)
    query_features = set(query.search.combined_features)
    if query.product_identity_names:
        identity_features = set().union(
            *(
                _features(name)
                for name in query.product_identity_names
            )
        )
        meaning_features.difference_update(identity_features)
        query_features.difference_update(identity_features)
    query_feature_sets = (source_features, meaning_features)
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
    safety_topic_required = (
        block.management_label == "safety_transcript"
    )
    source_grounding_overlap = _source_grounding_overlap(
        source_features=source_features,
        evidence_features=primary_features | qualifier_features,
        evidence_text=f"{primary_text} {qualifier_text}",
        safety_topic_required=safety_topic_required,
    )
    variant_coverage = _confirmed_variant_coverage(
        block,
        product_mention_features=product_variant_features,
    )
    safety_transcript_candidate = (
        query.safety_sensitive
        and safety_topic_required
        and bool(source_grounding_overlap)
    )
    if (
        not primary_overlap
        and not qualifier_overlap
        and variant_coverage <= 0
        and not safety_transcript_candidate
    ):
        return 0.0, []
    if (
        not source_grounding_overlap
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
        else (
            ["confirmed_variant_scope_match"]
            if variant_coverage > 0
            else ["safety_transcript_nomination"]
        )
    )
    source_coverage = (
        len(source_features & primary_features) / len(source_features)
        if source_features
        else 0.0
    )
    meaning_coverage = (
        len(meaning_features & primary_features)
        / len(meaning_features)
        if meaning_features
        else 0.0
    )
    if source_coverage > 0:
        score += source_coverage
        reasons.append("source_feature_coverage")
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

    compact_evidence = _compact(primary_text)
    descriptor_bonus = 0.0
    descriptor_reason: str | None = None
    for descriptor in block.free_descriptors:
        compact_descriptor = _compact(descriptor)
        if (
            len(compact_descriptor) >= 2
            and _features(compact_descriptor).issubset(query_features)
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
            query_unigrams = set(query.search.query_unigrams)
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
    if query_features and query_features.issubset(
        _features(compact_evidence)
    ):
        score += 3.0
        reasons.append("complete_query_feature_match")
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


def _source_grounding_overlap(
    *,
    source_features: set[str],
    evidence_features: set[str],
    evidence_text: str,
    safety_topic_required: bool,
) -> set[str]:
    ignored = (
        _SAFETY_LOW_INFORMATION_CJK
        if safety_topic_required
        else _LOW_INFORMATION_CJK
    )
    feature_overlap = source_features & evidence_features
    if safety_topic_required:
        feature_overlap = {
            feature
            for feature in feature_overlap
            if (
                not (characters := set(_CJK.findall(feature)))
                or len(characters - ignored) >= 2
            )
        }
    source_characters = {
        character
        for feature in source_features
        for character in feature
        if _CJK.fullmatch(character)
    } - ignored
    character_overlap = (
        source_characters & _cjk_unigrams(evidence_text)
    )
    if (
        safety_topic_required
        and not feature_overlap
        and len(character_overlap) < 2
    ):
        return set()
    return feature_overlap | character_overlap


def _include_unresolved_variant_relations(
    query: EvidenceQuery,
    ordered: list[EvidenceSelection],
    answerable: tuple[ProductEvidenceBlock, ...],
    *,
    product_variant_features: set[str],
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
        conflicting_scopes = _conflicting_variant_scopes(
            rows,
            product_variant_features=product_variant_features,
        )
        if conflicting_scopes is not None:
            ordered = [
                selection
                for selection in ordered
                if selection.evidence.variant_scope
                not in conflicting_scopes
            ]
            by_id = {
                selection.evidence.evidence_id: selection
                for selection in ordered
            }
            continue
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
            f"这款有多个{label}变体：{details}。"
            "购买前请核对所选或收到的具体规格。"
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


def _variant_value_features(value: str) -> set[str]:
    features = {
        token.casefold()
        for token in _ASCII_WORD.findall(value)
        if len(token) >= 2
    }
    for run in re.findall(r"[\u3400-\u9fff]+", value):
        if len(run) <= 3:
            features.add(run)
        else:
            features.update(
                run[index : index + 3]
                for index in range(len(run) - 2)
            )
    return features


def _has_explicit_variant_feature_match(
    mention_features: set[str],
    variant_features: set[str],
) -> bool:
    ascii_features = {
        feature
        for feature in variant_features
        if _ASCII_WORD.fullmatch(feature)
    }
    if mention_features & ascii_features:
        return True
    cjk_features = variant_features - ascii_features
    overlap = mention_features & cjk_features
    return bool(overlap) and (
        len(cjk_features) <= 2
        or (
            len(overlap) >= 2
            and len(overlap) * 2 >= len(cjk_features)
        )
    )


def _conflicting_variant_scopes(
    rows: list[tuple[ProductEvidenceBlock, str, str]],
    *,
    product_variant_features: set[str],
) -> frozenset[str] | None:
    if not product_variant_features:
        return None
    object_features = tuple(
        _variant_value_features(object_value)
        for _, _, object_value in rows
    )
    matched_indexes = {
        index
        for index, features in enumerate(object_features)
        if _has_explicit_variant_feature_match(
            product_variant_features,
            features
            - set().union(
                *(
                    other
                    for other_index, other in enumerate(object_features)
                    if other_index != index
                )
            )
        )
    }
    matched_objects = {
        _compact(rows[index][2])
        for index in matched_indexes
        if _compact(rows[index][2])
    }
    if len(matched_objects) != 1:
        return None
    return frozenset(
        block.variant_scope
        for index, (block, _, _) in enumerate(rows)
        if (
            index not in matched_indexes
            and block.variant_scope is not None
        )
    )


def _product_variant_features(
    query: EvidenceQuery,
    *,
    product_id: int,
) -> set[str]:
    if query.product_identity_names:
        product_index = query.product_ids.index(product_id)
        return _features(query.product_identity_names[product_index])
    if len(query.product_ids) == 1:
        return set(query.search.product_mention_features)
    return set()


def _query_specifies_variant_relation(
    query: EvidenceQuery,
    rows: list[tuple[ProductEvidenceBlock, str, str]],
) -> bool:
    query_features = set(query.search.combined_features)
    identity_names = {
        _compact(name)
        for name in query.product_identity_names
    }
    for _, subject, object_value in rows:
        object_features = _features(object_value)
        if (
            object_features
            and object_features.issubset(query_features)
        ):
            return True
        subject_features = _features(subject)
        if (
            subject_features
            and subject_features.issubset(query_features)
            and _compact(subject) not in identity_names
        ):
            return True
    return False


def _relation_dimension_is_relevant(
    query: EvidenceQuery,
    anchors: list[EvidenceSelection],
) -> bool:
    query_features = set(query.search.combined_features)
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
    product_mention_features: set[str],
) -> float:
    if (
        block.subject_scope != "exact_variant"
        or block.variant_scope is None
        or not product_mention_features
    ):
        return 0.0
    variant_features = _features(block.variant_scope)
    if not variant_features:
        return 0.0
    return (
        len(product_mention_features & variant_features)
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
    "PreparedEvidenceSearch",
    "ProductEvidenceRetriever",
    "prepare_evidence_search",
]
