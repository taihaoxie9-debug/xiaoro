from __future__ import annotations

import argparse
import csv
import json
import time
from pathlib import Path

from app.guide.adapters.catalog import CanonicalProductReader
from app.guide.application.contracts import UserTurn
from app.guide_runtime.composition import (
    compose_text_recommendation_orchestrator,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
CANONICAL = REPO_ROOT / "data" / "canonical"
CASES_PATH = (
    REPO_ROOT
    / "tests"
    / "fixtures"
    / "guide"
    / "slice1_backend_cases.json"
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    reader = CanonicalProductReader.from_files(
        manifest_path=CANONICAL / "core_products_v1_manifest.json",
        products_path=CANONICAL / "core_products_v1.jsonl",
    )
    orchestrator = compose_text_recommendation_orchestrator(reader)
    cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    rows: list[dict[str, str]] = []

    for case in cases:
        started = time.perf_counter()
        events = list(
            orchestrator.stream(
                UserTurn(
                    session_id=f"gate-{case['case_id']}",
                    message=case["message"],
                    image_bundle_id=None,
                    conversation_version=0,
                )
            )
        )
        elapsed_ms = (time.perf_counter() - started) * 1000
        products = next(
            (event for event in events if event.event == "products"),
            None,
        )
        decision = next(
            (
                event
                for event in events
                if event.event == "decision_process"
            ),
            None,
        )
        rows.append({
            "case_id": case["case_id"],
            "input_text": case["message"],
            "image_ids": "[]",
            "final_product_ids": json.dumps(
                [
                    card.product_id
                    for card in products.data.cards
                ]
                if products is not None
                else []
            ),
            "decision_status": (
                decision.data.winner_status
                if decision is not None
                else ""
            ),
            "failure_reason": (
                events[-1].data.code
                if events[-1].event == "error"
                else ""
            ),
            "latency_ms": f"{elapsed_ms:.3f}",
            "model_version": "not_used",
            "index_version": "not_used",
        })

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
