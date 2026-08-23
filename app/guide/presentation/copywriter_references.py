from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from types import MappingProxyType

from app.guide.presentation.copywriter_contracts import (
    PresentationPacket,
    build_copywriter_section_specs,
)


class CopywriterReferenceError(ValueError):
    """The model returned an evidence reference outside its prompt contract."""


@dataclass(frozen=True)
class CopywriterReferenceMap:
    fact_ref_by_id: Mapping[str, str]
    fact_id_by_ref: Mapping[str, str]
    constraint_ref_by_id: Mapping[str, str]
    constraint_id_by_ref: Mapping[str, str]


def build_copywriter_reference_map(
    packet: PresentationPacket,
) -> CopywriterReferenceMap:
    if not isinstance(packet, PresentationPacket):
        raise TypeError("packet must be PresentationPacket")
    specs = build_copywriter_section_specs(packet)
    allowed_fact_ids = _ordered_unique(
        fact_id
        for spec in specs
        for fact_id in spec.allowed_fact_ids
    )
    allowed_constraint_ids = _ordered_unique(
        constraint_id
        for spec in specs
        for constraint_id in spec.allowed_constraint_ids
    )
    available_fact_ids = {
        fact.fact_id
        for slot in packet.slots
        for fact in slot.approved_soft_facts
    }
    available_constraint_ids = {
        item.constraint_id
        for item in packet.approved_constraints
    }
    if not set(allowed_fact_ids) <= available_fact_ids:
        raise ValueError("writer fact reference is not packet-owned")
    if not set(allowed_constraint_ids) <= available_constraint_ids:
        raise ValueError("writer constraint reference is not packet-owned")
    fact_ref_by_id = {
        fact_id: f"f{index}"
        for index, fact_id in enumerate(allowed_fact_ids, start=1)
    }
    constraint_ref_by_id = {
        constraint_id: f"c{index}"
        for index, constraint_id in enumerate(
            allowed_constraint_ids,
            start=1,
        )
    }
    return CopywriterReferenceMap(
        fact_ref_by_id=MappingProxyType(fact_ref_by_id),
        fact_id_by_ref=MappingProxyType(
            {
                reference: fact_id
                for fact_id, reference in fact_ref_by_id.items()
            }
        ),
        constraint_ref_by_id=MappingProxyType(constraint_ref_by_id),
        constraint_id_by_ref=MappingProxyType(
            {
                reference: constraint_id
                for constraint_id, reference in (
                    constraint_ref_by_id.items()
                )
            }
        ),
    )


def expand_copywriter_evidence_references(
    packet: PresentationPacket,
    raw_output: object,
) -> object:
    if not isinstance(raw_output, dict):
        return raw_output
    reference_map = build_copywriter_reference_map(packet)
    expanded = deepcopy(raw_output)
    sections = expanded.get("sections")
    if not isinstance(sections, list):
        return expanded
    for section in sections:
        if not isinstance(section, dict):
            continue
        _expand_copy_block(
            section.get("content"),
            reference_map=reference_map,
        )
        _expand_copy_block(
            section.get("advisor_reason"),
            reference_map=reference_map,
        )
    return expanded


def bind_copywriter_fact_attribution(
    packet: PresentationPacket,
    raw_output: object,
) -> object:
    if not isinstance(raw_output, dict):
        return raw_output
    facts_by_id = {
        fact.fact_id: fact
        for slot in packet.slots
        for fact in slot.approved_soft_facts
    }
    bound = deepcopy(raw_output)
    sections = bound.get("sections")
    if not isinstance(sections, list):
        return bound
    for section in sections:
        if not isinstance(section, dict):
            continue
        for block in (
            section.get("content"),
            section.get("advisor_reason"),
        ):
            if not isinstance(block, dict):
                continue
            used_fact_ids = {
                fact_id
                for fact_id in block.get("used_fact_ids", ())
                if isinstance(fact_id, str)
            }
            attributions = {
                facts_by_id[fact_id].attribution
                for fact_id in used_fact_ids
                if fact_id in facts_by_id
            }
            prefix = _attribution_prefix(
                attributions=attributions,
            )
            if prefix:
                block["text"] = f"{prefix}{block.get('text')}"
    return bound


def _attribution_prefix(
    *,
    attributions: set[str],
) -> str:
    needs_merchant = "merchant_claim" in attributions
    needs_consumer = "consumer_report" in attributions
    if needs_merchant and needs_consumer:
        return "品牌主打与用户反馈："
    if needs_merchant:
        return "品牌主打："
    if needs_consumer:
        return "用户反馈："
    return ""


def _ordered_unique(values) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


def _expand_copy_block(
    raw_block: object,
    *,
    reference_map: CopywriterReferenceMap,
) -> None:
    if not isinstance(raw_block, dict):
        return
    _expand_reference_list(
        raw_block,
        field_name="used_fact_ids",
        ids_by_reference=reference_map.fact_id_by_ref,
    )
    _expand_reference_list(
        raw_block,
        field_name="used_constraint_ids",
        ids_by_reference=reference_map.constraint_id_by_ref,
    )


def _expand_reference_list(
    raw_block: dict[object, object],
    *,
    field_name: str,
    ids_by_reference: Mapping[str, str],
) -> None:
    references = raw_block.get(field_name)
    if references is None:
        return
    if not isinstance(references, list):
        return
    expanded: list[str] = []
    for reference in references:
        if not isinstance(reference, str):
            raise CopywriterReferenceError(
                f"{field_name} reference must be a string"
            )
        canonical_id = ids_by_reference.get(reference)
        if canonical_id is None:
            raise CopywriterReferenceError(
                f"unknown {field_name} reference"
            )
        expanded.append(canonical_id)
    raw_block[field_name] = expanded


__all__ = [
    "CopywriterReferenceError",
    "CopywriterReferenceMap",
    "bind_copywriter_fact_attribution",
    "build_copywriter_reference_map",
    "expand_copywriter_evidence_references",
]
