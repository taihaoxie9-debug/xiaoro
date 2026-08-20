from __future__ import annotations

from collections import Counter
import hashlib
import json
import re
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[4]
AUDIT_DIR = ROOT / "docs/audits/slice1.8"
AUDIT_JSON = AUDIT_DIR / "verified_absence_audit.json"
AUDIT_MARKDOWN = AUDIT_DIR / "verified_absence_audit.md"
CANONICAL = ROOT / "data/canonical"
CANONICAL_PRODUCTS = CANONICAL / "core_products_v1.jsonl"
SEED_DUMP = ROOT / "data/seed_dump.sql"

SUPPORTED_CATEGORIES = {
    "防晒",
    "防晒隔离",
    "防晒乳液",
    "防晒霜",
    "防晒乳",
    "精华",
    "精华液",
}
EXPECTED_SUPPORTED_PRODUCT_IDS = {
    26,
    32,
    33,
    34,
    35,
    36,
    37,
    38,
    39,
    40,
    41,
    42,
    51,
    52,
    53,
    54,
    55,
    56,
    57,
    58,
    59,
    63,
    91,
    101,
    102,
    105,
    129,
    130,
}
EXPECTED_SUPPORTED_CATEGORY_COUNTS = {
    "精华": 14,
    "精华液": 2,
    "防晒": 5,
    "防晒乳": 1,
    "防晒乳液": 4,
    "防晒隔离": 1,
    "防晒霜": 1,
}
SUNSCREEN_CATEGORIES = {
    "防晒",
    "防晒隔离",
    "防晒乳液",
    "防晒霜",
    "防晒乳",
}
SERUM_CATEGORIES = {"精华", "精华液"}
STRICT_FIELDS = {
    "product_id",
    "normalized_substance",
    "absence_quote",
    "formal_source_locator",
    "source_acquired_at",
    "source_class",
    "absence_review_decision_id",
    "absence_reviewer",
    "source_content_sha256",
}
SUBSTANCE_SLUGS = {
    "酒精": "alcohol",
    "色素": "colorant",
    "香精": "fragrance",
    "矿油": "mineral-oil",
    "尼泊金酯类防腐剂": "parabens",
    "防腐剂": "preservative",
}
EXPLICIT_ABSENCE = re.compile(
    r"不含|不添加|无添加|未添加|0添加|无香|无酒精|无色素|无矿油",
    re.IGNORECASE,
)
CONTROLLED_ABSENCE_RULES = (
    (
        "兰蔻极光水配方设计上不添加"
        "酒精、香精、色素、矿油、尼泊金酯类防腐剂",
        ("酒精", "香精", "色素", "矿油", "尼泊金酯类防腐剂"),
    ),
    (
        "未添加 色素、酒精、防腐剂、香精等刺激成分",
        ("色素", "酒精", "防腐剂", "香精"),
    ),
    (
        "本乳液使用无香配方，不含香精、色素、矿油",
        ("香精", "色素", "矿油"),
    ),
    ("无酒精无油配方", ("酒精",)),
    ("无香", ("香精",)),
)
CONTROLLED_UNNORMALIZED_RULES = (
    "不含致痘刺激成分",
    "无油配方",
)
DERIVED_OCR_SOURCE_CLASSES = {
    "detail_ocr_marketing",
    "ocr_html_enrich:key_ingredients",
}


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_path(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def read_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line
    ]


def read_audit() -> dict:
    return json.loads(AUDIT_JSON.read_text(encoding="utf-8"))


def read_copy_rows(
    path: Path,
    table: str,
) -> list[tuple[int, bytes, list[str]]]:
    header = f"COPY public.{table} (".encode()
    rows: list[tuple[int, bytes, list[str]]] = []
    in_table = False
    for line_number, source_line in enumerate(
        path.read_bytes().splitlines(keepends=True),
        start=1,
    ):
        if source_line.startswith(header):
            assert not in_table
            in_table = True
            continue
        if not in_table:
            continue
        if source_line.rstrip(b"\r\n") == b"\\.":
            return rows
        rows.append(
            (
                line_number,
                source_line,
                source_line.decode("utf-8").rstrip("\r\n").split("\t"),
            )
        )
    raise AssertionError(f"COPY table not found or unterminated: {table}")


def supported_canonical_products() -> dict[int, dict]:
    products = {
        row["product_id"]: row
        for row in read_jsonl(CANONICAL_PRODUCTS)
    }
    return {
        product_id: product
        for product_id, product in products.items()
        if product["fields"]["category"]["value"] in SUPPORTED_CATEGORIES
    }


def rebuild_seed_absence_inventory(
    supported_product_ids: set[int],
) -> tuple[
    set[tuple[str, int, int, str, str]],
    set[tuple[int, int, str, str]],
]:
    candidates_by_substance: dict[
        tuple[int, int, str],
        tuple[str, int, int, str, str],
    ] = {}
    excluded: set[tuple[int, int, str, str]] = set()

    for source_line, _source_bytes, columns in read_copy_rows(
        SEED_DUMP,
        "products",
    ):
        assert len(columns) == 20
        product_id = int(columns[0])
        if product_id not in supported_product_ids:
            continue
        source_text = "\t".join(columns)

        # Rules are ordered from the most specific statement to the shortest
        # fallback. A specific source quote wins when the row repeats a fact.
        for quote, normalized_substances in CONTROLLED_ABSENCE_RULES:
            if quote not in source_text:
                continue
            for normalized_substance in normalized_substances:
                key = (product_id, source_line, normalized_substance)
                candidate_id = (
                    f"p{product_id}-"
                    f"{SUBSTANCE_SLUGS[normalized_substance]}"
                )
                candidates_by_substance.setdefault(
                    key,
                    (
                        candidate_id,
                        product_id,
                        source_line,
                        quote,
                        normalized_substance,
                    ),
                )

        for quote in CONTROLLED_UNNORMALIZED_RULES:
            if quote in source_text:
                excluded.add(
                    (
                        product_id,
                        source_line,
                        quote,
                        "UNNORMALIZED_SUBSTANCE_CLASS",
                    )
                )

    return set(candidates_by_substance.values()), excluded


def is_missing(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, tuple, set, dict)):
        return not value
    return False


def parse_markdown_table(
    report: str,
    heading: str,
) -> list[dict[str, str]]:
    lines = report.splitlines()
    assert heading in lines, f"missing Markdown section: {heading}"
    index = lines.index(heading) + 1
    while index < len(lines) and not lines[index].startswith("|"):
        index += 1
    assert index + 1 < len(lines), f"missing table under: {heading}"

    def cells(line: str) -> list[str]:
        return [
            cell.strip().removeprefix("`").removesuffix("`")
            for cell in line.strip().strip("|").split("|")
        ]

    headers = cells(lines[index])
    separator = cells(lines[index + 1])
    assert len(separator) == len(headers)
    assert all(re.fullmatch(r":?-{3,}:?", item) for item in separator)

    rows: list[dict[str, str]] = []
    for line in lines[index + 2 :]:
        if not line.startswith("|"):
            break
        values = cells(line)
        assert len(values) == len(headers)
        rows.append(dict(zip(headers, values, strict=True)))
    return rows


def markdown_scalar(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return str(value).lower()
    return str(value)


def assert_markdown_matches_audit(audit: dict, report: str) -> None:
    summary_rows = parse_markdown_table(report, "## 结构化摘要")
    summary = {row["Key"]: row["Value"] for row in summary_rows}
    assert len(summary) == len(summary_rows)
    expected_summary = {
        "schema_version": audit["schema_version"],
        "recommendation": audit["recommendation"],
        "supported_product_ids": ",".join(
            str(item) for item in audit["scope"]["supported_product_ids"]
        ),
        **{
            f"supported_category:{category}": str(count)
            for category, count in audit["scope"][
                "supported_category_counts"
            ].items()
        },
        **{
            key: markdown_scalar(value)
            for key, value in audit["scan_counts"].items()
        },
        "canonical_sha_unchanged": markdown_scalar(
            all(
                item["sha256_before"] == item["sha256_after"]
                for item in audit["protected_assets"]
            )
        ),
    }
    assert summary == expected_summary

    candidate_rows = parse_markdown_table(report, "## 结构化候选")
    markdown_candidates = {
        row["Candidate ID"]: {
            "product_id": int(row["Product ID"]),
            "normalized_substance": row["Substance"],
            "source_line": int(row["Source line"]),
            "rejection_codes": sorted(
                code.strip()
                for code in row["Rejection codes"].split(",")
                if code.strip()
            ),
        }
        for row in candidate_rows
    }
    assert len(markdown_candidates) == len(candidate_rows)
    json_candidates = {
        item["candidate_id"]: {
            "product_id": item["product_id"],
            "normalized_substance": item["normalized_substance"],
            "source_line": item["source_line"],
            "rejection_codes": sorted(item["rejection_codes"]),
        }
        for item in audit["candidates"]
    }
    assert markdown_candidates == json_candidates

    sha_rows = parse_markdown_table(report, "## Canonical 保护值")
    markdown_shas = {
        row["Path"]: (row["SHA before"], row["SHA after"])
        for row in sha_rows
    }
    assert len(markdown_shas) == len(sha_rows)
    json_shas = {
        item["path"]: (item["sha256_before"], item["sha256_after"])
        for item in audit["protected_assets"]
    }
    assert markdown_shas == json_shas

    gate_rows = parse_markdown_table(report, "## 决策门检查点")
    markdown_gate = {row["Key"]: row["Value"] for row in gate_rows}
    assert len(markdown_gate) == len(gate_rows)
    expected_gate = {
        key: markdown_scalar(value)
        for key, value in audit["decision_gate"].items()
    }
    assert markdown_gate == expected_gate


def test_confirmed_no_go_locks_canonical_and_blocks_success_capability() -> None:
    audit = read_audit()

    assert audit["schema_version"] == "verified-absence-audit-v1"
    assert audit["recommendation"] == "NO-GO"
    assert audit["decision_gate"] == {
        "state": "CONFIRMED_NO_GO",
        "decision": "NO-GO",
        "token_checkpoint": "SLICE_1_8_COMPLETE_OR_CONFIRMED_NO_GO",
        "goal_id": "6a76acf2a50b6afe00c97e8c",
        "cumulative_tokens": 0,
        "stage_delta": 0,
        "token_observation": "GET_GOAL_CONFIRMED",
        "goal_status": "active",
        "head": "27c02b0ea93158bc0b866cdff53f7bc4def31ae1",
        "user_approval_recorded": True,
        "user_approval_statement": (
            "确认 Slice 1.8 采用 NO-GO：不修改 Canonical、"
            "不开放成分排除成功能力，并继续进入 Slice 1.9"
        ),
        "recorded_at": "2026-08-08T06:44:16Z",
        "task_4_6_complete": True,
        "canonical_change_authorized": False,
        "canonical_status": "UNCHANGED",
        "ingredient_exclusion_success_capability": "BLOCKED",
        "go_subtasks": "5.1,5.3,5.4=N/A_NO_GO",
        "next_stage": "SLICE_1_9",
    }
    assert audit["strict_admission_fields"] == sorted(STRICT_FIELDS)
    assert audit["scan_counts"] == {
        "canonical_products": 103,
        "supported_products": 28,
        "supported_sunscreen_products": 12,
        "supported_serum_products": 16,
        "review_decisions": 1234,
        "supported_review_decisions": 320,
        "verified_absence_review_decisions": 0,
        "seed_image_records": 103,
        "beauty_seed_products": 56,
        "candidate_source_products": 5,
        "candidate_facts": 14,
        "qualified_facts": 0,
        "rejected_facts": 14,
    }

    protected = audit["protected_assets"]
    assert len(protected) == 6
    for item in protected:
        path = ROOT / item["path"]
        assert item["sha256_before"] == item["sha256_after"]
        assert item["sha256_after"] == sha256_path(path)


def test_supported_scope_and_category_counts_rebuild_from_canonical() -> None:
    audit = read_audit()
    all_products = read_jsonl(CANONICAL_PRODUCTS)
    supported = supported_canonical_products()
    category_counts = Counter(
        item["fields"]["category"]["value"]
        for item in supported.values()
    )

    assert len(all_products) == 103
    assert set(supported) == EXPECTED_SUPPORTED_PRODUCT_IDS
    assert category_counts == EXPECTED_SUPPORTED_CATEGORY_COUNTS
    assert audit["scope"]["supported_product_ids"] == sorted(supported)
    assert audit["scope"]["supported_category_counts"] == dict(
        sorted(category_counts.items())
    )
    assert audit["scan_counts"]["canonical_products"] == len(all_products)
    assert audit["scan_counts"]["supported_products"] == len(supported)
    assert audit["scan_counts"]["supported_sunscreen_products"] == sum(
        category_counts[category]
        for category in SUNSCREEN_CATEGORIES
    )
    assert audit["scan_counts"]["supported_serum_products"] == sum(
        category_counts[category] for category in SERUM_CATEGORIES
    )


def test_candidates_exactly_match_controlled_seed_scan() -> None:
    audit = read_audit()
    supported_ids = set(supported_canonical_products())
    rebuilt_candidates, rebuilt_excluded = rebuild_seed_absence_inventory(
        supported_ids
    )
    recorded_candidates = {
        (
            item["candidate_id"],
            item["product_id"],
            item["source_line"],
            item["absence_quote"],
            item["normalized_substance"],
        )
        for item in audit["candidates"]
    }
    recorded_seed_exclusions = {
        (
            item["possible_product_id"],
            int(item["source"].rsplit(":", 1)[1]),
            item["quote"],
            item["reason_code"],
        )
        for item in audit["excluded_occurrences"]
        if item["source"].startswith("data/seed_dump.sql:")
    }

    assert recorded_candidates == rebuilt_candidates
    assert recorded_seed_exclusions == rebuilt_excluded
    assert audit["scan_counts"]["candidate_source_products"] == len(
        {item[1] for item in rebuilt_candidates}
    )
    assert audit["scan_counts"]["candidate_facts"] == len(
        rebuilt_candidates
    )


def test_candidates_are_explicit_but_fail_strict_admission() -> None:
    audit = read_audit()
    candidates = audit["candidates"]

    assert len(candidates) == 14
    assert len({item["candidate_id"] for item in candidates}) == 14
    assert not any(item["admission_result"] == "GO" for item in candidates)

    for item in candidates:
        assert STRICT_FIELDS <= item.keys()
        assert EXPLICIT_ABSENCE.search(item["absence_quote"])
        assert item["evidence_basis"] == "explicit_absence_statement"
        assert item["admission_result"] == "NO-GO"
        expected_missing = sorted(
            field for field in STRICT_FIELDS if is_missing(item[field])
        )
        assert item["missing_required_fields"] == expected_missing
        mapped_substances = next(
            substances
            for quote, substances in CONTROLLED_ABSENCE_RULES
            if quote == item["absence_quote"]
        )
        assert item["normalized_substance"] in mapped_substances
        if item["source_class"] in DERIVED_OCR_SOURCE_CLASSES:
            assert (
                "DERIVED_ENRICHMENT_NOT_PRIMARY_SOURCE"
                in item["rejection_codes"]
            )
        assert item["formal_source_locator"].startswith("https://")


def test_candidates_trace_to_supported_canonical_and_seed_rows() -> None:
    audit = read_audit()
    products = {
        row["product_id"]: row
        for row in read_jsonl(CANONICAL / "core_products_v1.jsonl")
    }
    seed_lines = SEED_DUMP.read_bytes().splitlines(keepends=True)

    for item in audit["candidates"]:
        product = products[item["product_id"]]
        assert item["category"] == product["fields"]["category"]["value"]
        assert (
            product["fields"]["verified_absences"]["resolved_state"]
            == "unknown"
        )

        source_line = seed_lines[item["source_line"] - 1]
        source_text = source_line.decode("utf-8")
        assert source_text.startswith(f"{item['product_id']}\t")
        assert item["absence_quote"] in source_text
        assert item["formal_source_locator"] in source_text
        assert item["source_record_sha256"] == sha256_bytes(source_line)


def test_review_inventory_has_no_absence_approval() -> None:
    audit = read_audit()
    decisions = read_jsonl(
        CANONICAL / "shadow_review_v1/review_decisions.jsonl"
    )
    absence_decisions = [
        item for item in decisions if item["facet_key"] == "verified_absences"
    ]

    assert absence_decisions == []
    assert audit["scan_counts"]["verified_absence_review_decisions"] == 0

    related = {
        item["product_id"]: item
        for item in audit["related_non_absence_reviews"]
    }
    assert set(related) == {53, 54, 55, 63, 91}
    for item in related.values():
        decision = next(
            row
            for row in decisions
            if row["decision_id"] == item["decision_id"]
        )
        assert decision["facet_key"] == "safety"
        assert decision["reviewer"] == item["reviewer"]
        assert item["not_absence_approval"] is True


def test_weak_inference_is_explicitly_rejected() -> None:
    audit = read_audit()

    assert audit["inference_policy"] == {
        "ingredient_list_difference": "REJECTED",
        "missing_ingredient_name": "REJECTED",
        "generic_safety_language": "REJECTED",
        "user_review_only": "REJECTED",
    }
    assert {
        item["reason_code"] for item in audit["excluded_occurrences"]
    } >= {
        "NON_FORMAL_KNOWLEDGE_SOURCE",
        "UNNORMALIZED_SUBSTANCE_CLASS",
    }
    assert all(
        item["evidence_basis"] != "ingredient_list_difference"
        for item in audit["candidates"]
    )
    for item in audit["excluded_occurrences"]:
        source_path, source_line = item["source"].rsplit(":", 1)
        source = ROOT / source_path
        line = source.read_text(encoding="utf-8").splitlines()[
            int(source_line) - 1
        ]
        assert item["quote"] in line
        if source_path.startswith("data/knowledge_docs/"):
            assert item["reason_code"] == "NON_FORMAL_KNOWLEDGE_SOURCE"
        else:
            assert source == SEED_DUMP
            assert (
                item["reason_code"] == "UNNORMALIZED_SUBSTANCE_CLASS"
            )


def test_markdown_report_structurally_matches_json() -> None:
    audit = read_audit()
    report = AUDIT_MARKDOWN.read_text(encoding="utf-8")
    assert_markdown_matches_audit(audit, report)


def test_markdown_verifier_rejects_each_critical_section_tamper() -> None:
    audit = read_audit()
    report = AUDIT_MARKDOWN.read_text(encoding="utf-8")
    tamperings = (
        ("| candidate_facts | 14 |", "| candidate_facts | 13 |"),
        (
            "| p53-fragrance | 53 | 香精 | 344 |",
            "| p53-fragrance | 54 | 香精 | 344 |",
        ),
        (
            "SOURCE_TERM_REQUIRES_REVIEW_NORMALIZATION",
            "REMOVED_REJECTION",
        ),
        (
            "0ba95df8c38d39f5bc0d73a32c318b157903abb64778c3e7b0acebfb75e95734",
            "f" * 64,
        ),
        (
            "| state | CONFIRMED_NO_GO |",
            "| state | GO |",
        ),
    )

    for original, replacement in tamperings:
        assert original in report
        with pytest.raises(AssertionError):
            assert_markdown_matches_audit(
                audit,
                report.replace(original, replacement, 1),
            )
