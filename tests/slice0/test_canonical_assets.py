from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CANONICAL = ROOT / "data/canonical"

EXPECTED = {
    "seed_dump": "ae45bbb513868619e578f63f252fff549ad62289aba0d474e2ae65aa754bc386",
    "products": "0ba95df8c38d39f5bc0d73a32c318b157903abb64778c3e7b0acebfb75e95734",
    "review_decisions": "12b0e1f82df3509ad8886af68a04ddcc62b28f3d3a5c72f4496ea22708fe50e9",
}


def sha256_path(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def manifest_digest(payload: dict) -> str:
    unsigned = {
        key: value
        for key, value in payload.items()
        if key != "manifest_sha256"
    }
    text = json.dumps(
        unsigned,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_jsonl(path: Path) -> list[dict]:
    rows = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        assert line.strip(), f"blank JSONL line: {line_number}"
        rows.append(json.loads(line))
    return rows


def test_canonical_assets_are_complete_and_hash_locked() -> None:
    products_path = CANONICAL / "core_products_v1.jsonl"
    products_manifest_path = CANONICAL / "core_products_v1_manifest.json"
    decisions_path = (
        CANONICAL / "shadow_review_v1/review_decisions.jsonl"
    )
    decisions_manifest_path = (
        CANONICAL
        / "shadow_review_v1/review_decisions_manifest.json"
    )
    seed_dump_path = ROOT / "data/seed_dump.sql"

    assert sha256_path(seed_dump_path) == EXPECTED["seed_dump"]
    assert sha256_path(products_path) == EXPECTED["products"]
    assert sha256_path(decisions_path) == EXPECTED["review_decisions"]

    products = read_jsonl(products_path)
    decisions = read_jsonl(decisions_path)
    assert len(products) == 103
    assert len(decisions) == 1234

    product_ids = {int(row["product_id"]) for row in products}
    reviewed_ids = {int(row["product_id"]) for row in decisions}
    assert len(product_ids) == 103
    assert reviewed_ids == product_ids

    products_manifest = json.loads(
        products_manifest_path.read_text(encoding="utf-8")
    )
    decisions_manifest = json.loads(
        decisions_manifest_path.read_text(encoding="utf-8")
    )

    assert products_manifest["product_count"] == 103
    assert products_manifest["products_sha256"] == EXPECTED["products"]
    assert (
        products_manifest["review_decisions_sha256"]
        == EXPECTED["review_decisions"]
    )
    assert (
        products_manifest["manifest_sha256"]
        == manifest_digest(products_manifest)
    )

    assert decisions_manifest["reviewed_products"] == 103
    assert decisions_manifest["total_decisions"] == 1234
    assert (
        decisions_manifest["review_decisions_sha256"]
        == EXPECTED["review_decisions"]
    )
    assert (
        decisions_manifest["manifest_sha256"]
        == manifest_digest(decisions_manifest)
    )
