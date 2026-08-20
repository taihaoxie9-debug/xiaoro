from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from tools.guide_gates.presentation_copy_gate import (
    PresentationCopyGateCase,
)


ROOT = Path(__file__).resolve().parents[2]
CANONICAL = ROOT / "data" / "canonical" / "core_products_v1.jsonl"
FACT_AUDIT = (
    ROOT
    / "docs"
    / "audits"
    / "continuous-conversation"
    / "presentation-fact-admission-v1.json"
)
DEFAULT_OUTPUT = (
    ROOT
    / "tests"
    / "fixtures"
    / "guide"
    / "presentation"
    / "copy_gate_v3_production.jsonl"
)
DEFAULT_MANIFEST = DEFAULT_OUTPUT.with_name(
    "copy_gate_v3_production_manifest.json"
)

_MERCHANT_MARKERS = ("商家", "主打", "品牌", "官方")
_CONSUMER_MARKERS = (
    "用户反馈",
    "使用者反馈",
    "限定样本",
    "样本反馈",
    "评论反馈",
)
_NO_CLOSING_MODES = {
    "comparison",
    "image_comparison",
    "image_identity",
    "image_suitability",
    "product_knowledge",
    "single_product",
    "general_knowledge",
    "consultation",
    "clarification",
}


@dataclass(frozen=True)
class SlotSpec:
    product_id: int
    category_profile: str
    fields: tuple[str, ...]
    include_consumer_report: bool = False


@dataclass(frozen=True)
class CaseSpec:
    case_id: str
    mode: str
    user_need_summary: str
    winner_status: str | None
    slots: tuple[SlotSpec, ...]
    forbidden_factual_claims: tuple[str, ...]


CASE_SPECS = (
    CaseSpec(
        "copy-001-recommendation",
        "recommendation",
        "油皮通勤防晒，希望看清肤感、成膜、适用肤质和清洁方式",
        "INSUFFICIENT_FOR_WINNER",
        (
            SlotSpec(
                55,
                "suncare",
                (
                    "texture",
                    "film_speed",
                    "suitable_skin",
                    "cleansing_requirement",
                    "sun_protection_spectrum",
                ),
            ),
        ),
        (
            "保证全天不需要补涂",
            "保证所有敏感肌都适用",
            "额外补水",
        ),
    ),
    CaseSpec(
        "copy-002-comparison",
        "comparison",
        "比较两款精华的功效、肤感和适用场景，并区分商家话术与用户反馈",
        "TIED",
        (
            SlotSpec(
                42,
                "skincare",
                ("efficacy", "texture"),
                include_consumer_report=True,
            ),
            SlotSpec(
                39,
                "skincare",
                ("efficacy", "texture", "suitable_skin"),
            ),
        ),
        ("用户反馈等于普遍效果", "价格更高所以效果更强"),
    ),
    CaseSpec(
        "copy-003-single-product",
        "single_product",
        "判断这款洁面是否适合日常使用，重点看泡沫、洗后肤感和清洁边界",
        "NOT_APPLICABLE",
        (
            SlotSpec(
                66,
                "cleanser",
                (
                    "texture",
                    "rinse_behavior",
                    "suitable_skin",
                    "cleansing_power",
                ),
            ),
        ),
        ("可以卸除所有浓妆", "保证适合所有肤质"),
    ),
    CaseSpec(
        "copy-004-product-knowledge",
        "product_knowledge",
        "只说明这款眼霜的功效定位、质地和精确商品信息",
        None,
        (SlotSpec(72, "skincare", ("efficacy", "texture")),),
        ("可以治疗黑眼圈", "七天保证见效"),
    ),
    CaseSpec(
        "copy-005-general-knowledge",
        "general_knowledge",
        "解释防晒补涂时应该考虑用量、出汗、摩擦和使用场景",
        None,
        (),
        ("任何场景都不用补涂", "一次涂抹全天有效"),
    ),
    CaseSpec(
        "copy-006-followup",
        "followup",
        "延续上一轮清透防晒，补充说明轻薄肤感、成膜和清洁方式",
        "INSUFFICIENT_FOR_WINNER",
        (
            SlotSpec(
                55,
                "suncare",
                ("texture", "film_speed", "cleansing_requirement"),
            ),
        ),
        ("已经满足全部要求", "无需再核对实际肤感"),
    ),
    CaseSpec(
        "copy-007-revision",
        "revision",
        "改为千元左右抗初老精华，完整说明功效、肤感、香调和适用肤质",
        "INSUFFICIENT_FOR_WINNER",
        (
            SlotSpec(
                39,
                "skincare",
                (
                    "suitable_skin",
                    "texture",
                    "efficacy",
                    "fragrance_description",
                    "efficacy",
                ),
            ),
        ),
        ("保证修复所有屏障问题", "可以代替医学治疗"),
    ),
    CaseSpec(
        "copy-008-image-identity",
        "image_identity",
        "图片商品身份已确认，只围绕该气垫的妆效、肤感、持妆和适用肤质说明",
        "NOT_APPLICABLE",
        (
            SlotSpec(
                109,
                "base_makeup",
                (
                    "finish",
                    "texture",
                    "efficacy",
                    "longevity",
                    "suitable_skin",
                ),
            ),
        ),
        ("图片证明适合所有人", "保证完全不卡纹"),
    ),
    CaseSpec(
        "copy-009-image-recommendation",
        "image_recommendation",
        "根据已确认的气垫商品路线给出底妆建议，保留真实妆效和肤感边界",
        "INSUFFICIENT_FOR_WINNER",
        (
            SlotSpec(
                109,
                "base_makeup",
                ("finish", "texture", "longevity", "suitable_skin"),
            ),
        ),
        ("保证全天不脱妆", "保证所有肤质都不卡粉"),
    ),
    CaseSpec(
        "copy-010-image-suitability",
        "image_suitability",
        "判断图片中的防晒是否适合偏油肤质，说明质地、收尾、场景和防水边界",
        "NOT_APPLICABLE",
        (
            SlotSpec(
                57,
                "suncare",
                (
                    "texture",
                    "finish",
                    "usage_context",
                    "water_resistance",
                ),
            ),
        ),
        ("保证油皮绝不搓泥", "防水等于无需补涂"),
    ),
    CaseSpec(
        "copy-011-image-comparison",
        "image_comparison",
        "按图片顺序比较两款底妆的质地、妆效、持妆和适用肤质",
        "TIED",
        (
            SlotSpec(
                109,
                "base_makeup",
                ("texture", "finish", "longevity"),
            ),
            SlotSpec(
                112,
                "base_makeup",
                ("texture", "finish", "longevity"),
            ),
        ),
        ("第一张一定更适合所有人", "两款都保证全天持妆"),
    ),
    CaseSpec(
        "copy-012-consultation",
        "consultation",
        "整理清洁后紧绷的当前观察，并继续询问必要信息",
        None,
        (),
        ("已经确诊皮炎", "可以代替医生诊断"),
    ),
    CaseSpec(
        "copy-013-recommendation-three-products",
        "recommendation",
        "三款防晒都在预算内，分别说明轻薄度、成膜、使用场景和取舍",
        "INSUFFICIENT_FOR_WINNER",
        (
            SlotSpec(
                55,
                "suncare",
                ("texture", "film_speed", "suitable_skin"),
            ),
            SlotSpec(
                57,
                "suncare",
                ("texture", "usage_context", "water_resistance"),
            ),
            SlotSpec(
                58,
                "suncare",
                ("texture", "finish", "film_speed"),
            ),
        ),
        ("三款都绝对适合敏感肌", "防晒力全天不衰减"),
    ),
    CaseSpec(
        "copy-014-recommendation-no-winner",
        "recommendation",
        "预算内想看清爽防晒，但现有信息不足以指定唯一首选",
        "INSUFFICIENT_FOR_WINNER",
        (
            SlotSpec(
                55,
                "suncare",
                (
                    "texture",
                    "film_speed",
                    "suitable_skin",
                    "cleansing_requirement",
                    "sun_protection_spectrum",
                ),
            ),
        ),
        ("保证防晒效果", "所有人都适用"),
    ),
    CaseSpec(
        "copy-015-comparison-evidence-boundary",
        "comparison",
        "比较两款精华时，明确区分商家主打和限定样本的用户反馈",
        "TIED",
        (
            SlotSpec(
                42,
                "skincare",
                ("efficacy", "texture"),
                include_consumer_report=True,
            ),
            SlotSpec(
                39,
                "skincare",
                ("efficacy", "texture"),
            ),
        ),
        ("商家宣称等于独立验证", "消费者反馈适用于所有人"),
    ),
    CaseSpec(
        "copy-016-product-knowledge-usage",
        "product_knowledge",
        "只回答当前眼霜的日常定位、质地和精确商品事实，不展开综合推荐",
        None,
        (SlotSpec(72, "skincare", ("efficacy", "texture")),),
        ("可以治疗眼周问题", "所有人都能每天使用"),
    ),
    CaseSpec(
        "copy-017-general-knowledge-evidence",
        "general_knowledge",
        "解释商家宣称、消费者反馈与审核事实在导购中的区别",
        None,
        (),
        ("商家宣称等于独立验证", "消费者反馈适用于所有人"),
    ),
    CaseSpec(
        "copy-018-consultation-correction",
        "consultation",
        "用户纠正前一轮观察，需要清楚说明本轮更新并继续确认",
        None,
        (),
        ("已经确诊敏感肌", "旧观察仍然确定成立"),
    ),
    CaseSpec(
        "copy-019-consultation-safety",
        "consultation",
        "当前出现破皮和渗出，需要给出停止尝试与就医提醒",
        None,
        (),
        ("继续叠加新品观察", "可以自行治疗感染"),
    ),
    CaseSpec(
        "copy-020-clarification",
        "clarification",
        "多张图片指代不明确，需要请用户指定图片序号",
        None,
        (),
        ("默认选择第一张", "已经确认具体商品"),
    ),
)


def _load_jsonl(path: Path) -> tuple[dict[str, Any], ...]:
    return tuple(
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    )


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _display_value(value: object) -> str:
    if isinstance(value, list):
        return "、".join(str(item).strip() for item in value if str(item).strip())
    return str(value).strip()


def _merchant_facts(
    *,
    rows: tuple[dict[str, Any], ...],
    product_id: int,
    fields: tuple[str, ...],
) -> tuple[dict[str, Any], ...]:
    available = tuple(
        row
        for row in rows
        if (
            row["product_id"] == product_id
            and row["disposition"] == "positioning"
            and row["packet_fact_id"] is not None
        )
    )
    selected: list[dict[str, Any]] = []
    used_ids: set[str] = set()
    used_meanings: set[str] = set()
    for field_key in fields:
        match = next(
            (
                row
                for row in available
                if (
                    row["field_key"] == field_key
                    and row["packet_fact_id"] not in used_ids
                    and row["plain_meaning"] not in used_meanings
                )
            ),
            None,
        )
        if match is None:
            raise ValueError(
                f"missing production fact product={product_id} "
                f"field={field_key}"
            )
        selected.append(match)
        used_ids.add(match["packet_fact_id"])
        used_meanings.add(match["plain_meaning"])
    return tuple(selected)


def _direct_facts(
    *,
    inventory: tuple[dict[str, Any], ...],
    product_id: int,
) -> tuple[dict[str, Any], ...]:
    direct = tuple(
        row
        for row in inventory
        if (
            row["product_id"] == product_id
            and row["presentation_role"] == "direct_fact"
        )
    )
    return direct[:1]


def _slot(
    *,
    spec: SlotSpec,
    canonical: dict[int, dict[str, Any]],
    audit_rows: tuple[dict[str, Any], ...],
    review_inventory: tuple[dict[str, Any], ...],
    category_inventory: tuple[dict[str, Any], ...],
) -> tuple[dict[str, Any], tuple[dict[str, Any], ...]]:
    product = canonical.get(spec.product_id)
    if product is None:
        raise ValueError(f"missing Canonical product {spec.product_id}")
    fields = product["fields"]
    identity = fields["product_identity"]
    price = fields["price"]
    if (
        identity["resolved_state"] != "known"
        or price["resolved_state"] != "known"
    ):
        raise ValueError(
            f"product {spec.product_id} lacks known identity or price"
        )

    source_records: list[dict[str, Any]] = []
    soft_facts: list[dict[str, Any]] = []
    for row in _merchant_facts(
        rows=audit_rows,
        product_id=spec.product_id,
        fields=spec.fields,
    ):
        soft_facts.append({
            "fact_id": row["packet_fact_id"],
            "field_key": row["field_key"],
            "plain_meaning": row["plain_meaning"],
            "attribution": "merchant_claim",
        })
        source_records.append({
            "fact_id": row["packet_fact_id"],
            "product_id": spec.product_id,
            "attribution": "merchant_claim",
            "source_refs": row["source_refs"],
        })

    if spec.include_consumer_report:
        review = next(
            (
                row
                for row in review_inventory
                if row["product_id"] == spec.product_id
            ),
            None,
        )
        if review is None:
            raise ValueError(
                f"missing approved review for product {spec.product_id}"
            )
        fact_id = f"consumer-report:{review['content_sha256']}"
        soft_facts.append({
            "fact_id": fact_id,
            "field_key": "consumer_report",
            "plain_meaning": (
                f"限定样本的用户反馈：{review['content']}"
            ),
            "attribution": "consumer_report",
        })
        source_records.append({
            "fact_id": fact_id,
            "product_id": spec.product_id,
            "attribution": "consumer_report",
            "source_refs": [review["source_locator"]],
        })

    locked_facts = [{
        "fact_id": f"canonical-price:{spec.product_id}",
        "kind": "price",
        "label": "参考价",
        "display_value": f"¥{float(price['value']):.2f}",
    }]
    for direct in _direct_facts(
        inventory=category_inventory,
        product_id=spec.product_id,
    ):
        field_key = direct["field_key"]
        locked_facts.append({
            "fact_id": f"direct:{spec.product_id}:{field_key}",
            "kind": (
                "specification"
                if field_key == "net_content"
                else "numeric"
            ),
            "label": {
                "net_content": "规格",
                "spf_pa": "防晒值",
                "sun_protection_claim": "防晒说明",
            }.get(field_key, field_key),
            "display_value": _display_value(direct["value"]),
        })
        source_records.append({
            "fact_id": f"direct:{spec.product_id}:{field_key}",
            "product_id": spec.product_id,
            "attribution": "verified_fact",
            "source_refs": direct["source_refs"],
        })

    return (
        {
            "slot_id": "",
            "product_id": spec.product_id,
            "name": identity["value"],
            "category_profile": spec.category_profile,
            "soft_facts": soft_facts,
            "locked_facts": locked_facts,
            "cautions": [],
        },
        tuple(source_records),
    )


def build_copy_gate_v3() -> tuple[bytes, dict[str, Any]]:
    canonical = {
        row["product_id"]: row for row in _load_jsonl(CANONICAL)
    }
    audit = json.loads(FACT_AUDIT.read_text(encoding="utf-8"))
    audit_rows = tuple(audit["rows"])
    review_inventory = tuple(audit["review_inventory"])
    category_inventory = tuple(audit["category_fact_inventory"])

    case_rows: list[dict[str, Any]] = []
    source_records: list[dict[str, Any]] = []
    for spec in CASE_SPECS:
        slots: list[dict[str, Any]] = []
        for index, slot_spec in enumerate(spec.slots, start=1):
            slot, sources = _slot(
                spec=slot_spec,
                canonical=canonical,
                audit_rows=audit_rows,
                review_inventory=review_inventory,
                category_inventory=category_inventory,
            )
            slot["slot_id"] = f"p{index}"
            slots.append(slot)
            source_records.extend(
                {
                    **source,
                    "case_id": spec.case_id,
                    "slot_id": f"p{index}",
                }
                for source in sources
            )

        required_slots = [slot["slot_id"] for slot in slots]
        allowed_soft_fact_ids = {
            slot["slot_id"]: [
                fact["fact_id"] for fact in slot["soft_facts"]
            ]
            for slot in slots
        }
        locked_atoms = [
            fact["display_value"]
            for slot in slots
            for fact in slot["locked_facts"]
        ]
        required_attribution = [
            {
                "slot_id": slot["slot_id"],
                "fact_id": fact["fact_id"],
                "attribution": fact["attribution"],
                "accepted_markers": (
                    list(_MERCHANT_MARKERS)
                    if fact["attribution"] == "merchant_claim"
                    else list(_CONSUMER_MARKERS)
                ),
            }
            for slot in slots
            for fact in slot["soft_facts"]
        ]
        require_closing = spec.mode not in _NO_CLOSING_MODES
        row = {
            "schema_version": "guide-presentation-copy-gate-v1",
            "case_id": spec.case_id,
            "mode": spec.mode,
            "user_need_summary": spec.user_need_summary,
            "winner_status": spec.winner_status,
            "slots": slots,
            "required_slots": required_slots,
            "allowed_soft_fact_ids": allowed_soft_fact_ids,
            "locked_atoms": locked_atoms,
            "winner_language_policy": "forbidden",
            "required_attribution": required_attribution,
            "forbidden_factual_claims": list(
                spec.forbidden_factual_claims
            ),
            "readability": {
                "summary_min_chars": 12,
                "product_field_min_chars": 8 if slots else 1,
                "closing_min_chars": 10 if require_closing else 0,
                "require_closing": require_closing,
                "require_soft_fact_use": bool(slots),
            },
            "dont_care_wording": [
                "punctuation",
                "sentence_order",
                "synonymous_advisor_copy",
            ],
        }
        PresentationCopyGateCase.model_validate(row, strict=True)
        case_rows.append(row)

    if [row["case_id"] for row in case_rows] != sorted(
        row["case_id"] for row in case_rows
    ):
        raise ValueError("production copy gate cases must be sorted")
    fixture = b"".join(
        _canonical_json(row) + b"\n" for row in case_rows
    )
    manifest = {
        "schema_version": "guide-presentation-copy-gate-production-v3",
        "case_count": len(case_rows),
        "fixture_sha256": sha256(fixture).hexdigest(),
        "canonical_sha256": sha256(CANONICAL.read_bytes()).hexdigest(),
        "fact_admission_sha256": sha256(
            FACT_AUDIT.read_bytes()
        ).hexdigest(),
        "product_ids": sorted({
            slot["product_id"]
            for row in case_rows
            for slot in row["slots"]
        }),
        "mode_counts": dict(sorted(Counter(
            row["mode"] for row in case_rows
        ).items())),
        "source_facts": source_records,
    }
    return fixture, manifest


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    fixture, manifest = build_copy_gate_v3()
    output = Path(args.output)
    manifest_path = Path(args.manifest)
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(fixture)
    manifest_path.write_bytes(_canonical_json(manifest) + b"\n")
    print(json.dumps({
        "status": "ok",
        "case_count": manifest["case_count"],
        "fixture_sha256": manifest["fixture_sha256"],
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
