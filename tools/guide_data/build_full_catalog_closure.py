"""Build deterministic full-catalog saved-page closure evidence."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import stat
from types import MappingProxyType
from typing import Literal, Mapping
from urllib.parse import parse_qs, urlsplit

from app.guide.retrieval.category_fact_contracts import (
    SourceClass,
    category_field_registry,
)
from app.guide.retrieval.category_profiles import (
    CategoryProfile,
    category_profile_for,
)
from tools.guide_data.extract_saved_page_evidence import (
    SavedPageError,
    SavedPageEvidence,
    extract_saved_page_evidence,
)
from tools.guide_data.inventory_local_sources import (
    atomic_write_private,
)
from tools.guide_data.read_seed_dump_products import (
    SeedProductRow,
    read_seed_dump_products,
)


BindingStatus = Literal[
    "exact_item",
    "alternate_equivalent",
    "source_gap",
    "unbound",
]
ParameterDisposition = Literal[
    "pending",
    "quarantine",
    "not_applicable",
]


@dataclass(frozen=True, slots=True)
class ParameterRule:
    field_key: str
    safety_sensitive: bool = False


@dataclass(frozen=True, slots=True)
class SpecialProductBinding:
    status: Literal["alternate_equivalent", "source_gap"]
    alternate_item_id: str | None
    required_title_markers: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ParameterClassification:
    classification_id: str
    product_id: int | None
    category_profile: CategoryProfile | None
    binding_status: BindingStatus
    source_class: str
    source_sha256: str
    source_locator: str
    item_id: str
    sku_ids: tuple[str, ...]
    parameter_name: str
    parameter_name_sha256: str
    raw_value_sha256: str
    normalized_value_sha256: str
    normalized_value: object
    field_key: str | None
    disposition: ParameterDisposition
    capability_ceiling: frozenset[str]
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FullCatalogClosureReport:
    inventory_count: int
    saved_page_count: int
    parseable_page_count: int
    parameter_group_count: int
    silently_skipped: int
    canonical_product_count: int
    exact_item_product_count: int
    alternate_equivalent_product_count: int
    source_gap_product_count: int
    product_matrix_count: int
    pending_candidate_count: int
    quarantine_candidate_count: int
    source_observation_count: int
    artifact_sha256: dict[str, str]


_SPECIAL_PRODUCT_BINDINGS = MappingProxyType(
    {
        36: SpecialProductBinding(
            status="alternate_equivalent",
            alternate_item_id="100092327970",
            required_title_markers=(
                "玉兰油",
                "第4代",
                "小白瓶",
                "40ml",
                "ProX",
            ),
        ),
        53: SpecialProductBinding(
            status="source_gap",
            alternate_item_id=None,
        ),
        70: SpecialProductBinding(
            status="alternate_equivalent",
            alternate_item_id="100238733259",
            required_title_markers=(
                "贝德玛",
                "粉水",
                "洁肤液",
                "500ml",
            ),
        ),
        106: SpecialProductBinding(
            status="source_gap",
            alternate_item_id=None,
        ),
        144: SpecialProductBinding(
            status="alternate_equivalent",
            alternate_item_id="2387902",
            required_title_markers=(
                "玉泽",
                "神经酰胺",
                "调理乳",
                "100ml",
            ),
        ),
    }
)


_COMMON_RULES = {
    "使用方法": ParameterRule("usage"),
    "净含量": ParameterRule("net_content"),
    "保质期": ParameterRule("shelf_life"),
    "化妆品保质期": ParameterRule("shelf_life"),
    "产地": ParameterRule("origin"),
    "适用人群": ParameterRule("target_audience"),
    "适用对象": ParameterRule("target_audience"),
    "适用性别": ParameterRule("target_audience"),
    "使用场景": ParameterRule("usage_context"),
    "适用场景": ParameterRule("usage_context"),
    "适用场合": ParameterRule("usage_context"),
    "适用季节": ParameterRule("usage_context"),
    "适用部位": ParameterRule("application_area"),
    "适合肤质": ParameterRule("suitable_skin"),
    "适用肤质": ParameterRule("suitable_skin"),
    "质地": ParameterRule("texture"),
    "是否为特殊用途化妆品": ParameterRule(
        "safety",
        safety_sensitive=True,
    ),
    "是否特殊化妆品": ParameterRule(
        "safety",
        safety_sensitive=True,
    ),
    "化妆品备案编号/注册证号": ParameterRule(
        "safety",
        safety_sensitive=True,
    ),
    "批准文号/备案编号": ParameterRule(
        "safety",
        safety_sensitive=True,
    ),
    "医疗器械注册证编号或者备案凭证编号": ParameterRule(
        "safety",
        safety_sensitive=True,
    ),
    "产品技术要求编号": ParameterRule(
        "safety",
        safety_sensitive=True,
    ),
    "生产许可证或者备案凭证编号": ParameterRule(
        "safety",
        safety_sensitive=True,
    ),
    "禁忌症": ParameterRule(
        "safety",
        safety_sensitive=True,
    ),
    "注册信息": ParameterRule(
        "safety",
        safety_sensitive=True,
    ),
    "原料成分": ParameterRule(
        "ingredients_present",
        safety_sensitive=True,
    ),
    "主要成分": ParameterRule(
        "ingredients_present",
        safety_sensitive=True,
    ),
    "主要功效成分": ParameterRule(
        "ingredients_present",
        safety_sensitive=True,
    ),
    "核心成分": ParameterRule(
        "ingredients_present",
        safety_sensitive=True,
    ),
    "微量成分": ParameterRule(
        "ingredients_present",
        safety_sensitive=True,
    ),
    "结构及组成": ParameterRule(
        "ingredients_present",
        safety_sensitive=True,
    ),
    "适用范围": ParameterRule(
        "efficacy",
        safety_sensitive=True,
    ),
}


def _rules(**items: str) -> Mapping[str, ParameterRule]:
    values = dict(_COMMON_RULES)
    values.update(
        {
            alias: ParameterRule(field_key)
            for alias, field_key in items.items()
        }
    )
    return MappingProxyType(values)


_PARAMETER_REGISTRIES = MappingProxyType(
    {
        CategoryProfile.SKINCARE: _rules(
            功效="efficacy",
            核心功效="efficacy",
            肤质问题="skin_concern",
            针对肤质问题="skin_concern",
            面膜分类="product_form",
            膜布材质="mask_material",
            香味="fragrance_description",
            单盒片数="package_quantity",
            盒数="package_quantity",
            包装数量="package_quantity",
        ),
        CategoryProfile.SUNCARE: _rules(
            功效="efficacy",
            防晒指数="spf_pa",
            PA值="spf_pa",
            防晒标准="spf_pa",
            防晒分类="product_form",
            成膜速度="film_speed",
            防晒光谱="sun_protection_spectrum",
            是否修色提亮="tone_effect",
            颜色分类="variant_option",
        ),
        CategoryProfile.BASE_MAKEUP: _rules(
            功效="efficacy",
            核心功效="efficacy",
            颜色="variant_option",
            颜色分类="variant_option",
            色号="shade",
            妆效="finish",
            遮瑕分类="product_form",
            遮瑕产品分类="product_form",
            遮瑕部位="application_area",
            防晒指数="spf_pa",
            是否防晒="sun_protection_claim",
            是否含防晒="sun_protection_claim",
            粉底分类="product_form",
        ),
        CategoryProfile.COLOR_MAKEUP: _rules(
            功效="efficacy",
            颜色="variant_option",
            颜色分类="variant_option",
            色号="shade",
            妆效="finish",
            色系="color_family",
            颜色数="color_count",
            形态="product_form",
        ),
        CategoryProfile.CLEANSER: _rules(
            功效="efficacy",
            洁面分类="cleansing_form",
            洁面单品="cleansing_form",
            卸妆单品="cleansing_form",
            卸妆效果="cleansing_power",
            起泡程度="rinse_behavior",
            香型="fragrance_description",
        ),
        CategoryProfile.FRAGRANCE: _rules(
            香调="fragrance_family",
            香型分类="fragrance_family",
            香味="fragrance_family",
            香型="fragrance_family",
            香水分类="fragrance_family",
        ),
    }
)


def parameter_registries() -> Mapping[
    CategoryProfile,
    Mapping[str, ParameterRule],
]:
    return _PARAMETER_REGISTRIES


def special_product_bindings() -> Mapping[int, SpecialProductBinding]:
    return _SPECIAL_PRODUCT_BINDINGS


def parameter_rule_for(
    profile: CategoryProfile | None,
    parameter_name: str,
    raw_values: tuple[str, ...] | None = None,
) -> ParameterRule | None:
    if profile is not None and not isinstance(profile, CategoryProfile):
        raise TypeError("profile must be CategoryProfile or None")
    if not isinstance(parameter_name, str):
        raise TypeError("parameter_name must be str")
    if profile is None:
        return None
    normalized_name = _normalize_text(parameter_name)
    normalized_values = (
        tuple(_normalize_text(value) for value in raw_values)
        if raw_values is not None
        else None
    )
    handled, value_rule = _value_sensitive_rule(
        profile=profile,
        parameter_name=normalized_name,
        raw_values=normalized_values,
    )
    rule = (
        value_rule
        if handled
        else _PARAMETER_REGISTRIES[profile].get(normalized_name)
    )
    if rule is None:
        return None
    profile_fields = {
        definition.key
        for definition in category_field_registry().for_profile(profile)
    }
    return rule if rule.field_key in profile_fields else None


def _value_sensitive_rule(
    *,
    profile: CategoryProfile,
    parameter_name: str,
    raw_values: tuple[str, ...] | None,
) -> tuple[bool, ParameterRule | None]:
    if raw_values is None:
        return False, None
    combined = " ".join(raw_values)
    if (
        profile is CategoryProfile.SKINCARE
        and parameter_name == "针对肤质问题"
    ):
        if combined in {"其他", "其它", "无", "不详"}:
            return True, None
        if any(
            marker in combined
            for marker in (
                "肤质",
                "敏感肌",
                "敏感性",
                "油性",
                "干性",
                "混合性",
            )
        ):
            return True, ParameterRule("suitable_skin")
        return True, ParameterRule("skin_concern")
    if parameter_name in {"产地", "产品产地"}:
        if combined.casefold() in {
            "其他",
            "其它",
            "other",
            "其他/other",
            "未知",
            "不详",
        }:
            return True, None
        if any(
            marker in combined
            for marker in ("以实物为准", "批次不同")
        ):
            return True, None
        return True, ParameterRule("origin")
    return False, None


def classify_parameter_group(
    *,
    product_id: int | None,
    category_profile: CategoryProfile | None,
    binding_status: BindingStatus,
    source_sha256: str,
    item_id: str,
    sku_ids: tuple[str, ...],
    parameter_name: str,
    raw_values: tuple[str, ...],
    ordinal: int,
    canonical_state: str | None = None,
) -> ParameterClassification:
    _validate_classification_inputs(
        product_id=product_id,
        source_sha256=source_sha256,
        item_id=item_id,
        sku_ids=sku_ids,
        parameter_name=parameter_name,
        raw_values=raw_values,
        ordinal=ordinal,
    )
    normalized_name = _normalize_text(parameter_name)
    raw_value = tuple(_normalize_text(value) for value in raw_values)
    raw_value_sha256 = _value_sha256(list(raw_value))
    rule = parameter_rule_for(
        category_profile,
        normalized_name,
        raw_value,
    )
    normalized_value = (
        _normalize_for_field(rule.field_key, raw_value)
        if rule is not None
        else list(raw_value)
    )
    normalized_value_sha256 = _value_sha256(normalized_value)
    parameter_name_sha256 = _sha256(normalized_name.encode("utf-8"))
    source_locator = (
        f"urn:xiaoro:saved-page:sha256:{source_sha256}:"
        f"item:{item_id}:skus:{','.join(sku_ids)}:"
        f"parameter:{ordinal:04d}:{parameter_name_sha256}:"
        f"raw:{raw_value_sha256}:normalized:{normalized_value_sha256}"
    )

    if rule is None:
        disposition: ParameterDisposition = "not_applicable"
        reasons = ("outside_recommendation_registry",)
        capabilities: frozenset[str] = frozenset({"evidence"})
        field_key = None
    elif binding_status == "alternate_equivalent":
        disposition = "quarantine"
        reasons = ("alternate_equivalent_requires_review",)
        capabilities = frozenset({"evidence"})
        field_key = rule.field_key
    elif binding_status in {"source_gap", "unbound"} or product_id is None:
        disposition = "quarantine"
        reasons = ("product_source_binding_missing",)
        capabilities = frozenset({"evidence"})
        field_key = rule.field_key
    elif canonical_state == "known":
        disposition = "quarantine"
        reasons = ("canonical_field_already_known",)
        capabilities = frozenset({"evidence"})
        field_key = rule.field_key
    elif canonical_state == "conflict":
        disposition = "quarantine"
        reasons = ("canonical_field_conflict",)
        capabilities = frozenset({"evidence"})
        field_key = rule.field_key
    elif rule.safety_sensitive:
        disposition = "quarantine"
        reasons = ("insufficient_safety_authority",)
        capabilities = frozenset({"evidence"})
        field_key = rule.field_key
    else:
        disposition = "pending"
        reasons = ()
        field_key = rule.field_key
        assert category_profile is not None
        capabilities = _merchant_capabilities(
            category_profile,
            field_key,
        )

    identity_payload = {
        "binding_status": binding_status,
        "category_profile": (
            category_profile.value
            if category_profile is not None
            else None
        ),
        "disposition": disposition,
        "field_key": field_key,
        "item_id": item_id,
        "normalized_value_sha256": normalized_value_sha256,
        "ordinal": ordinal,
        "parameter_name_sha256": parameter_name_sha256,
        "product_id": product_id,
        "raw_value_sha256": raw_value_sha256,
        "sku_ids": list(sku_ids),
        "source_class": SourceClass.MERCHANT_PARAMETER.value,
        "source_locator": source_locator,
        "source_sha256": source_sha256,
    }
    return ParameterClassification(
        classification_id=_value_sha256(identity_payload),
        product_id=product_id,
        category_profile=category_profile,
        binding_status=binding_status,
        source_class=SourceClass.MERCHANT_PARAMETER.value,
        source_sha256=source_sha256,
        source_locator=source_locator,
        item_id=item_id,
        sku_ids=sku_ids,
        parameter_name=normalized_name,
        parameter_name_sha256=parameter_name_sha256,
        raw_value_sha256=raw_value_sha256,
        normalized_value_sha256=normalized_value_sha256,
        normalized_value=normalized_value,
        field_key=field_key,
        disposition=disposition,
        capability_ceiling=capabilities,
        reasons=reasons,
    )


def build_full_catalog_closure(
    *,
    inventory_path: str | Path,
    downloads_root: str | Path,
    seed_dump_path: str | Path,
    canonical_products_path: str | Path,
    output_dir: str | Path,
    expected_inventory_sha256: str,
    expected_inventory_count: int,
    expected_saved_page_count: int,
    expected_parseable_page_count: int,
    expected_parameter_group_count: int,
    expected_canonical_product_count: int,
    expected_exact_item_product_count: int,
) -> FullCatalogClosureReport:
    inventory_rows = _load_inventory(
        Path(inventory_path),
        expected_sha256=expected_inventory_sha256,
        expected_count=expected_inventory_count,
    )
    saved_rows = tuple(
        row
        for row in inventory_rows
        if (
            row["source_root_id"] == _downloads_root_id()
            and row["content_type"] == "html"
            and _is_top_level_name(str(row["relative_name"]))
        )
    )
    if len(saved_rows) != expected_saved_page_count:
        raise ValueError("saved page count does not match frozen gate")

    canonical_products = _load_canonical_products(
        Path(canonical_products_path)
    )
    if len(canonical_products) != expected_canonical_product_count:
        raise ValueError("canonical product count does not match gate")
    product_ids = tuple(sorted(canonical_products))
    seed_rows = read_seed_dump_products(
        seed_dump_path,
        product_ids=product_ids,
    )
    seed_by_product = {
        row.product_id: row
        for row in seed_rows
    }
    products_by_item: dict[str, list[int]] = defaultdict(list)
    for row in seed_rows:
        item_id = _item_id_from_url(row.detail_url)
        if item_id is None:
            raise ValueError(
                f"seed product {row.product_id} has no item identity"
            )
        products_by_item[item_id].append(row.product_id)

    page_manifest: list[dict[str, object]] = []
    parsed_pages: list[SavedPageEvidence] = []
    for inventory_row in sorted(
        saved_rows,
        key=lambda row: str(row["relative_name"]),
    ):
        relative_name = str(inventory_row["relative_name"])
        relative_name_sha256 = _sha256(
            relative_name.encode("utf-8")
        )
        source_path = Path(downloads_root) / relative_name
        try:
            evidence = extract_saved_page_evidence(source_path)
        except SavedPageError as exc:
            page_manifest.append(
                {
                    "error": str(exc),
                    "parse_status": "error",
                    "relative_name_sha256": relative_name_sha256,
                    "source_sha256": inventory_row["sha256"],
                }
            )
            continue
        if evidence.source_sha256 != inventory_row["sha256"]:
            raise ValueError("saved page source SHA drift")
        parsed_pages.append(evidence)
        page_manifest.append(
            {
                "item_id": evidence.item_id,
                "parameter_group_count": len(evidence.parameters),
                "parse_status": "parsed",
                "platform": evidence.platform,
                "relative_name_sha256": relative_name_sha256,
                "review_count": len(evidence.reviews),
                "sku_ids": list(evidence.sku_ids),
                "source_sha256": evidence.source_sha256,
                "title_sha256": _sha256(
                    evidence.title.encode("utf-8")
                ),
            }
        )
    if len(parsed_pages) != expected_parseable_page_count:
        raise ValueError("parseable saved page count does not match gate")

    page_bindings = _bind_pages(
        parsed_pages,
        products_by_item=products_by_item,
        canonical_product_ids=set(product_ids),
    )
    profiles = {
        product_id: _canonical_profile(canonical_products[product_id])
        for product_id in product_ids
    }
    classifications: list[ParameterClassification] = []
    source_observations: list[dict[str, object]] = []
    for page in sorted(
        parsed_pages,
        key=lambda item: (item.source_sha256, item.item_id),
    ):
        product_id, binding_status = page_bindings[
            page.source_sha256
        ]
        profile = profiles.get(product_id)
        source_observations.append(
            _source_observation(
                source_class=SourceClass.MERCHANT_TITLE_CLAIM,
                source_sha256=page.source_sha256,
                item_id=page.item_id,
                sku_ids=page.sku_ids,
                locator_suffix="title",
                value=page.title,
                authority_scope="merchant_claim",
            )
        )
        for review in page.reviews:
            source_observations.append(
                _source_observation(
                    source_class=SourceClass.CONSUMER_REVIEW,
                    source_sha256=page.source_sha256,
                    item_id=page.item_id,
                    sku_ids=(
                        (review.sku_id,)
                        if review.sku_id
                        else page.sku_ids
                    ),
                    locator_suffix=(
                        "review:"
                        + _sha256(review.feed_id.encode("utf-8"))
                    ),
                    value=review.content,
                    authority_scope="experience_only",
                )
            )
        for ordinal, (name, values) in enumerate(
            sorted(page.parameters.items()),
            start=1,
        ):
            rule = parameter_rule_for(profile, name, values)
            canonical_state = (
                _canonical_field_state(
                    canonical_products[product_id],
                    rule.field_key,
                )
                if (
                    product_id is not None
                    and rule is not None
                )
                else None
            )
            classifications.append(
                classify_parameter_group(
                    product_id=product_id,
                    category_profile=profile,
                    binding_status=binding_status,
                    source_sha256=page.source_sha256,
                    item_id=page.item_id,
                    sku_ids=page.sku_ids,
                    parameter_name=name,
                    raw_values=values,
                    ordinal=ordinal,
                    canonical_state=canonical_state,
                )
            )
    if len(classifications) != expected_parameter_group_count:
        raise ValueError("parameter group count does not match gate")

    binding_by_product = _product_binding_statuses(
        product_ids=product_ids,
        seed_by_product=seed_by_product,
        parsed_pages=parsed_pages,
        page_bindings=page_bindings,
    )
    exact_count = sum(
        status == "exact_item"
        for status in binding_by_product.values()
    )
    if exact_count != expected_exact_item_product_count:
        raise ValueError("exact-item product count does not match gate")

    candidates = _promotion_candidates(tuple(classifications))
    quarantine = _promotion_quarantine(tuple(classifications))
    matrix = [
        build_product_state_row(
            canonical_product=canonical_products[product_id],
            category_profile=profiles[product_id],
            binding_status=binding_by_product[product_id],
            classifications=tuple(classifications),
        )
        for product_id in product_ids
    ]
    artifacts = {
        "page_manifest.jsonl": _render_jsonl(page_manifest),
        "parameter_classifications.jsonl": render_classifications(
            tuple(classifications)
        ),
        "pending_candidates.jsonl": _render_jsonl(candidates),
        "quarantine_candidates.jsonl": _render_jsonl(quarantine),
        "product_matrix.jsonl": _render_jsonl(matrix),
        "source_observations.jsonl": _render_jsonl(
            source_observations
        ),
    }
    artifact_sha256 = {
        name: _sha256(content)
        for name, content in sorted(artifacts.items())
    }
    report = FullCatalogClosureReport(
        inventory_count=len(inventory_rows),
        saved_page_count=len(saved_rows),
        parseable_page_count=len(parsed_pages),
        parameter_group_count=len(classifications),
        silently_skipped=(
            sum(len(page.parameters) for page in parsed_pages)
            - len(classifications)
        ),
        canonical_product_count=len(canonical_products),
        exact_item_product_count=exact_count,
        alternate_equivalent_product_count=sum(
            status == "alternate_equivalent"
            for status in binding_by_product.values()
        ),
        source_gap_product_count=sum(
            status == "source_gap"
            for status in binding_by_product.values()
        ),
        product_matrix_count=len(matrix),
        pending_candidate_count=len(candidates),
        quarantine_candidate_count=len(quarantine),
        source_observation_count=len(source_observations),
        artifact_sha256=artifact_sha256,
    )
    if report.silently_skipped != 0:
        raise ValueError("parameter groups were silently skipped")

    summary = {
        **{
            name: getattr(report, name)
            for name in FullCatalogClosureReport.__dataclass_fields__
            if name != "artifact_sha256"
        },
        "artifact_sha256": artifact_sha256,
        "binding_status_counts": {
            status: sum(
                observed == status
                for observed in binding_by_product.values()
            )
            for status in (
                "exact_item",
                "alternate_equivalent",
                "source_gap",
            )
        },
        "inventory_sha256": expected_inventory_sha256,
        "matrix_state_counts": {
            state: sum(
                int(row["state_counts"][state])
                for row in matrix
            )
            for state in (
                "known",
                "pending",
                "quarantine",
                "unknown",
                "not_applicable",
            )
        },
        "schema_version": "full-catalog-closure-v1",
    }
    artifacts["summary.json"] = _canonical_json_bytes(summary) + b"\n"
    for name, content in sorted(artifacts.items()):
        atomic_write_private(
            Path(output_dir) / name,
            content,
        )
    return report


def promotion_candidate_row(
    classification: ParameterClassification,
) -> dict[str, object]:
    if not isinstance(classification, ParameterClassification):
        raise TypeError(
            "classification must be ParameterClassification"
        )
    if (
        classification.disposition != "pending"
        or classification.product_id is None
        or classification.field_key is None
        or classification.category_profile is None
    ):
        raise ValueError(
            "only bound pending classifications can be promoted"
        )
    row: dict[str, object] = {
        "candidate_id": "",
        "category_profile": classification.category_profile.value,
        "conflict_candidate_ids": [],
        "conflict_group_id": None,
        "extraction_method": "structured_json",
        "field_key": classification.field_key,
        "has_conflict": False,
        "normalized_value": classification.normalized_value,
        "product_id": classification.product_id,
        "source_class": classification.source_class,
        "source_locator": classification.source_locator,
        "source_sha256": classification.source_sha256,
        "status": "pending",
        "value_sha256": classification.normalized_value_sha256,
    }
    row["candidate_id"] = _sha256(
        (
            f"{classification.product_id}\0"
            f"{classification.category_profile.value}\0"
            f"{classification.field_key}\0"
            f"{classification.source_sha256}\0"
            f"{classification.source_locator}\0"
            f"{_canonical_json_text(classification.normalized_value)}"
        ).encode("utf-8")
    )
    return row


def build_product_state_row(
    *,
    canonical_product: dict[str, object],
    category_profile: CategoryProfile,
    binding_status: BindingStatus,
    classifications: tuple[ParameterClassification, ...],
) -> dict[str, object]:
    product_id = canonical_product.get("product_id")
    fields = canonical_product.get("fields")
    if (
        isinstance(product_id, bool)
        or not isinstance(product_id, int)
        or product_id <= 0
        or not isinstance(fields, dict)
    ):
        raise ValueError("canonical product is invalid")
    relevant = tuple(
        item
        for item in classifications
        if item.product_id == product_id
    )
    definitions = category_field_registry().definitions
    field_states: dict[str, str] = {}
    for definition in definitions:
        if category_profile not in definition.profiles:
            field_states[definition.key] = "not_applicable"
            continue
        canonical_field = fields.get(definition.key)
        canonical_state = (
            canonical_field.get("resolved_state")
            if isinstance(canonical_field, dict)
            else None
        )
        if canonical_state == "known":
            field_states[definition.key] = "known"
            continue
        if canonical_state == "conflict":
            field_states[definition.key] = "quarantine"
            continue
        field_rows = tuple(
            item
            for item in relevant
            if item.field_key == definition.key
        )
        if any(item.disposition == "pending" for item in field_rows):
            field_states[definition.key] = "pending"
        elif any(
            item.disposition == "quarantine"
            for item in field_rows
        ):
            field_states[definition.key] = "quarantine"
        else:
            field_states[definition.key] = "unknown"

    state_counts = {
        state: sum(
            observed == state
            for observed in field_states.values()
        )
        for state in (
            "known",
            "pending",
            "quarantine",
            "unknown",
            "not_applicable",
        )
    }
    core_ready = all(
        field_states.get(field_key) == "known"
        for field_key in (
            "product_identity",
            "brand",
            "category",
            "price",
        )
    )
    if binding_status in {"source_gap", "unbound"}:
        readiness = "source_gap"
    elif binding_status == "alternate_equivalent" or not core_ready:
        readiness = "partial"
    else:
        readiness = "ready"
    return {
        "binding_status": binding_status,
        "category_profile": category_profile.value,
        "field_states": field_states,
        "product_id": product_id,
        "readiness": readiness,
        "state_counts": state_counts,
    }


def render_classifications(
    classifications: tuple[ParameterClassification, ...],
) -> bytes:
    rows = sorted(
        (
            {
                "binding_status": item.binding_status,
                "capability_ceiling": sorted(
                    item.capability_ceiling
                ),
                "category_profile": (
                    item.category_profile.value
                    if item.category_profile is not None
                    else None
                ),
                "classification_id": item.classification_id,
                "disposition": item.disposition,
                "field_key": item.field_key,
                "item_id": item.item_id,
                "normalized_value": item.normalized_value,
                "normalized_value_sha256": (
                    item.normalized_value_sha256
                ),
                "parameter_name": item.parameter_name,
                "parameter_name_sha256": (
                    item.parameter_name_sha256
                ),
                "product_id": item.product_id,
                "raw_value_sha256": item.raw_value_sha256,
                "reasons": list(item.reasons),
                "sku_ids": list(item.sku_ids),
                "source_class": item.source_class,
                "source_locator": item.source_locator,
                "source_sha256": item.source_sha256,
            }
            for item in classifications
        ),
        key=lambda row: str(row["classification_id"]),
    )
    return b"".join(
        _canonical_json_bytes(row) + b"\n"
        for row in rows
    )


def _downloads_root_id() -> str:
    return _sha256(
        b"guide-source-root-v1\0approved-root-0001"
    )


def _load_inventory(
    path: Path,
    *,
    expected_sha256: str,
    expected_count: int,
) -> tuple[dict[str, object], ...]:
    metadata = path.lstat()
    if path.is_symlink() or not stat.S_ISREG(metadata.st_mode):
        raise ValueError("inventory must be a regular file")
    content = path.read_bytes()
    if _sha256(content) != expected_sha256:
        raise ValueError("inventory SHA-256 mismatch")
    expected_fields = {
        "content_type",
        "relative_name",
        "sha256",
        "size_bytes",
        "source_root_id",
    }
    rows: list[dict[str, object]] = []
    for line_number, line in enumerate(content.splitlines(), start=1):
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"inventory line {line_number} is invalid"
            ) from exc
        if not isinstance(row, dict) or set(row) != expected_fields:
            raise ValueError(
                f"inventory line {line_number} shape is invalid"
            )
        if (
            not isinstance(row["relative_name"], str)
            or not isinstance(row["content_type"], str)
            or not isinstance(row["source_root_id"], str)
            or not isinstance(row["sha256"], str)
            or len(str(row["sha256"])) != 64
            or isinstance(row["size_bytes"], bool)
            or not isinstance(row["size_bytes"], int)
            or row["size_bytes"] < 0
        ):
            raise ValueError(
                f"inventory line {line_number} values are invalid"
            )
        rows.append(row)
    if len(rows) != expected_count:
        raise ValueError("inventory row count mismatch")
    ordering = [
        (
            str(row["sha256"]),
            str(row["relative_name"]),
            str(row["source_root_id"]),
        )
        for row in rows
    ]
    if ordering != sorted(ordering):
        raise ValueError("inventory rows must retain frozen ordering")
    return tuple(rows)


def _is_top_level_name(value: str) -> bool:
    candidate = Path(value)
    return (
        value not in {"", ".", ".."}
        and not candidate.is_absolute()
        and candidate.name == value
        and "/" not in value
        and "\\" not in value
    )


def _load_canonical_products(
    path: Path,
) -> dict[int, dict[str, object]]:
    metadata = path.lstat()
    if path.is_symlink() or not stat.S_ISREG(metadata.st_mode):
        raise ValueError("canonical products must be a regular file")
    rows: dict[int, dict[str, object]] = {}
    for line_number, line in enumerate(
        path.read_bytes().splitlines(),
        start=1,
    ):
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"canonical row {line_number} is invalid"
            ) from exc
        if not isinstance(row, dict):
            raise ValueError("canonical product row must be an object")
        product_id = row.get("product_id")
        fields = row.get("fields")
        if (
            isinstance(product_id, bool)
            or not isinstance(product_id, int)
            or product_id <= 0
            or not isinstance(fields, dict)
            or product_id in rows
        ):
            raise ValueError("canonical product identity is invalid")
        rows[product_id] = row
    return rows


def _item_id_from_url(value: str | None) -> str | None:
    if not value:
        return None
    parsed = urlsplit(value)
    query_values = parse_qs(parsed.query).get("id", [])
    if (
        len(query_values) == 1
        and query_values[0].isdigit()
    ):
        return query_values[0]
    match = re.search(
        r"/(?:product/)?([0-9]+)\.html$",
        parsed.path,
    )
    return match.group(1) if match is not None else None


def _bind_pages(
    pages: list[SavedPageEvidence],
    *,
    products_by_item: dict[str, list[int]],
    canonical_product_ids: set[int],
) -> dict[str, tuple[int | None, BindingStatus]]:
    alternates = {
        binding.alternate_item_id: (product_id, binding)
        for product_id, binding in _SPECIAL_PRODUCT_BINDINGS.items()
        if (
            binding.alternate_item_id is not None
            and product_id in canonical_product_ids
        )
    }
    bindings: dict[str, tuple[int | None, BindingStatus]] = {}
    for page in pages:
        exact_products = products_by_item.get(page.item_id, [])
        if len(exact_products) == 1:
            binding: tuple[int | None, BindingStatus] = (
                exact_products[0],
                "exact_item",
            )
        elif len(exact_products) > 1:
            binding = (None, "unbound")
        else:
            alternate = alternates.get(page.item_id)
            if alternate is None:
                binding = (None, "unbound")
            else:
                product_id, specification = alternate
                normalized_title = page.title.casefold()
                if all(
                    marker.casefold() in normalized_title
                    for marker in specification.required_title_markers
                ):
                    binding = (
                        product_id,
                        "alternate_equivalent",
                    )
                else:
                    binding = (None, "unbound")
        bindings[page.source_sha256] = binding
    if len(bindings) != len(pages):
        raise ValueError("saved page source SHA values must be unique")
    return bindings


def _canonical_profile(
    canonical_product: dict[str, object],
) -> CategoryProfile:
    fields = canonical_product["fields"]
    assert isinstance(fields, dict)
    category = fields.get("category")
    value = (
        category.get("value")
        if isinstance(category, dict)
        else None
    )
    if not isinstance(value, str):
        raise ValueError("canonical category is invalid")
    try:
        return category_profile_for(value)
    except KeyError as exc:
        raise ValueError("canonical category is unmapped") from exc


def _canonical_field_state(
    canonical_product: dict[str, object],
    field_key: str,
) -> str | None:
    fields = canonical_product["fields"]
    assert isinstance(fields, dict)
    field = fields.get(field_key)
    state = (
        field.get("resolved_state")
        if isinstance(field, dict)
        else None
    )
    return state if isinstance(state, str) else None


def _source_observation(
    *,
    source_class: SourceClass,
    source_sha256: str,
    item_id: str,
    sku_ids: tuple[str, ...],
    locator_suffix: str,
    value: str,
    authority_scope: str,
) -> dict[str, object]:
    value_sha256 = _sha256(
        _normalize_text(value).encode("utf-8")
    )
    return {
        "authority_scope": authority_scope,
        "item_id": item_id,
        "sku_ids": list(sku_ids),
        "source_class": source_class.value,
        "source_locator": (
            f"urn:xiaoro:saved-page:sha256:{source_sha256}:"
            f"item:{item_id}:skus:{','.join(sku_ids)}:"
            f"{locator_suffix}:value:{value_sha256}"
        ),
        "source_sha256": source_sha256,
        "value_sha256": value_sha256,
    }


def _product_binding_statuses(
    *,
    product_ids: tuple[int, ...],
    seed_by_product: dict[int, SeedProductRow],
    parsed_pages: list[SavedPageEvidence],
    page_bindings: dict[str, tuple[int | None, BindingStatus]],
) -> dict[int, BindingStatus]:
    if set(seed_by_product) != set(product_ids):
        raise ValueError("seed and canonical product sets differ")
    observed: dict[int, set[BindingStatus]] = defaultdict(set)
    for page in parsed_pages:
        product_id, status = page_bindings[page.source_sha256]
        if product_id is not None:
            observed[product_id].add(status)
    statuses: dict[int, BindingStatus] = {}
    for product_id in product_ids:
        values = observed.get(product_id, set())
        if "exact_item" in values:
            statuses[product_id] = "exact_item"
        elif "alternate_equivalent" in values:
            statuses[product_id] = "alternate_equivalent"
        else:
            statuses[product_id] = "source_gap"
    return statuses


def _promotion_candidates(
    classifications: tuple[ParameterClassification, ...],
) -> list[dict[str, object]]:
    grouped: dict[
        tuple[int, str],
        list[ParameterClassification],
    ] = defaultdict(list)
    for item in classifications:
        if (
            item.disposition == "pending"
            and item.product_id is not None
            and item.field_key is not None
        ):
            grouped[(item.product_id, item.field_key)].append(item)
    rows: list[dict[str, object]] = []
    for items in grouped.values():
        if len(
            {
                item.normalized_value_sha256
                for item in items
            }
        ) != 1:
            continue
        selected = min(
            items,
            key=lambda item: item.classification_id,
        )
        rows.append(promotion_candidate_row(selected))
    return sorted(rows, key=lambda row: str(row["candidate_id"]))


def _promotion_quarantine(
    classifications: tuple[ParameterClassification, ...],
) -> list[dict[str, object]]:
    rows = [
        {
            "candidate_id": item.classification_id,
            "category_profile": (
                item.category_profile.value
                if item.category_profile is not None
                else "unbound"
            ),
            "extraction_method": "structured_json",
            "field_key": item.field_key or "unregistered_parameter",
            "product_id": item.product_id,
            "quarantine_reasons": list(item.reasons),
            "source_class": item.source_class,
            "source_locator": item.source_locator,
            "source_sha256": item.source_sha256,
            "status": "quarantine",
            "value_sha256": item.normalized_value_sha256,
        }
        for item in classifications
        if item.disposition == "quarantine"
    ]
    return sorted(rows, key=lambda row: str(row["candidate_id"]))


def _render_jsonl(rows: list[dict[str, object]]) -> bytes:
    return b"".join(
        _canonical_json_bytes(row) + b"\n"
        for row in sorted(rows, key=_row_sort_key)
    )


def _row_sort_key(row: dict[str, object]) -> str:
    for field in (
        "candidate_id",
        "classification_id",
        "product_id",
        "source_locator",
        "relative_name_sha256",
    ):
        value = row.get(field)
        if value is not None:
            return f"{field}:{value}"
    return _canonical_json_text(row)


def _merchant_capabilities(
    profile: CategoryProfile,
    field_key: str,
) -> frozenset[str]:
    definition = next(
        item
        for item in category_field_registry().for_profile(profile)
        if item.key == field_key
    )
    policy = next(
        item
        for item in definition.source_policies
        if item.source_class is SourceClass.MERCHANT_PARAMETER
    )
    return policy.capabilities


def _normalize_for_field(
    field_key: str,
    values: tuple[str, ...],
) -> object:
    definition = next(
        item
        for item in category_field_registry().definitions
        if item.key == field_key
    )
    unique = tuple(sorted(set(values)))
    if definition.value_type == "string_list":
        return list(unique)
    if definition.value_type == "string":
        return " / ".join(unique)
    return list(unique)


def _validate_classification_inputs(
    *,
    product_id: int | None,
    source_sha256: str,
    item_id: str,
    sku_ids: tuple[str, ...],
    parameter_name: str,
    raw_values: tuple[str, ...],
    ordinal: int,
) -> None:
    if (
        product_id is not None
        and (
            isinstance(product_id, bool)
            or not isinstance(product_id, int)
            or product_id <= 0
        )
    ):
        raise ValueError("product_id must be a positive integer or None")
    if (
        len(source_sha256) != 64
        or any(character not in "0123456789abcdef" for character in source_sha256)
    ):
        raise ValueError("source_sha256 must be lowercase SHA-256")
    if not item_id.isdigit():
        raise ValueError("item_id must be numeric")
    if (
        not sku_ids
        or sku_ids != tuple(sorted(set(sku_ids)))
        or any(not sku_id.isdigit() for sku_id in sku_ids)
    ):
        raise ValueError("sku_ids must be sorted unique numeric IDs")
    if not _normalize_text(parameter_name):
        raise ValueError("parameter_name must be non-empty")
    if not raw_values or any(not _normalize_text(value) for value in raw_values):
        raise ValueError("raw_values must be non-empty strings")
    if isinstance(ordinal, bool) or not isinstance(ordinal, int) or ordinal < 1:
        raise ValueError("ordinal must be a positive integer")


def _normalize_text(value: str) -> str:
    return " ".join(value.split()).strip()


def _value_sha256(value: object) -> str:
    return _sha256(
        json.dumps(
            value,
            ensure_ascii=True,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    )


def _canonical_json_text(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _canonical_json_bytes(value: object) -> bytes:
    return _canonical_json_text(value).encode("utf-8")


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


__all__ = [
    "BindingStatus",
    "ParameterClassification",
    "ParameterDisposition",
    "ParameterRule",
    "SpecialProductBinding",
    "build_product_state_row",
    "classify_parameter_group",
    "parameter_registries",
    "parameter_rule_for",
    "promotion_candidate_row",
    "render_classifications",
    "special_product_bindings",
]
