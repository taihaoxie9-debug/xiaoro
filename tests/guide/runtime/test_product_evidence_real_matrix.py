from __future__ import annotations

import json
from pathlib import Path

from app.guide.application.contracts import UserTurn
from app.guide.understanding.contracts import (
    TopicCode,
    UnderstandingGoal,
)
from app.guide.understanding.semantic_contracts import (
    SemanticContext,
    SemanticIntentProposal,
    SemanticProductMention,
    SemanticReference,
)
from app.guide_runtime.composition import build_runtime_orchestrator


ROOT = Path(__file__).resolve().parents[3]
MATRIX_PATH = (
    ROOT
    / "docs"
    / "audits"
    / "product-evidence"
    / "real_question_matrix.jsonl"
)


def _matrix_rows() -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in MATRIX_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


class MatrixSemanticPort:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._by_message: dict[str, dict[str, object]] = {}
        for row in rows:
            message = str(row["message"])
            translator = dict(row["translator"])
            previous = self._by_message.setdefault(message, translator)
            assert previous == translator

    def propose(
        self,
        message: str,
        context: SemanticContext,
    ) -> SemanticIntentProposal:
        del context
        values = self._by_message[message]
        mentions = []
        for text in values["mention_texts"]:
            start = message.index(text)
            mentions.append(
                SemanticProductMention(
                    text=text,
                    start=start,
                    end=start + len(text),
                )
            )
        references = tuple(
            SemanticReference.model_validate(item, strict=True)
            for item in values["references"]
        )
        return SemanticIntentProposal(
            goal=UnderstandingGoal(values["goal"]),
            topic=(
                TopicCode(values["topic"])
                if values["topic"] is not None
                else None
            ),
            concerns=(),
            observations=(),
            references=references,
            product_mentions=tuple(mentions),
            confidence=0.99,
            clarification_hint=None,
            question_meaning=values["question_meaning"],
            safety_sensitive=values["safety_sensitive"],
        )


def test_real_question_matrix_closes_production_runtime(
    tmp_path: Path,
) -> None:
    rows = _matrix_rows()
    runtime = build_runtime_orchestrator(
        state_dir=tmp_path / "matrix-state",
        semantic_intent=MatrixSemanticPort(rows),
    )

    assert len(rows) == 30
    for row in rows:
        expected = row["expected"]
        events = list(
            runtime.stream(
                UserTurn(
                    session_id=row["session_id"],
                    message=row["message"],
                    image_bundle_id=None,
                    conversation_version=row[
                        "conversation_version"
                    ],
                )
            )
        )
        event_names = [event.event for event in events]
        assert "error" not in event_names, row["case_id"]
        assert (
            ("clarify" in event_names)
            is expected["clarification"]
        ), row["case_id"]
        intent = next(
            event for event in events if event.event == "intent"
        )
        assert intent.data.mode == expected["mode"], row["case_id"]

        evidence = next(
            event
            for event in events
            if event.event == "product_evidence"
        )
        packet = evidence.data.packet
        assert list(packet.query.product_ids) == expected[
            "product_ids"
        ], row["case_id"]
        if expected["first_evidence_id"] is not None:
            assert packet.selected, row["case_id"]
            assert (
                packet.selected[0].evidence.evidence_id
                == expected["first_evidence_id"]
            ), row["case_id"]
        if row["question_kind"] == "no_evidence":
            assert not packet.selected, row["case_id"]
            assert packet.missing_aspects, row["case_id"]
        assert bool(packet.safety_caveats) is expected[
            "safety_caveat"
        ], row["case_id"]

        visible_product_ids = expected["visible_product_ids"]
        if visible_product_ids:
            products = next(
                event
                for event in events
                if event.event == "products"
            )
            assert [
                card.product_id for card in products.data.cards
            ] == visible_product_ids, row["case_id"]
            assert event_names.index(
                "decision_process"
            ) < event_names.index("product_evidence"), row["case_id"]

        messages = [
            event.data.content
            for event in events
            if event.event == "message"
        ]
        combined_message = "\n".join(messages)
        for value in expected["answer_contains"]:
            assert value in combined_message, row["case_id"]
        for value in expected["answer_forbids"]:
            assert value not in combined_message, row["case_id"]

        assert events[-1].event == "end", row["case_id"]
        assert events[-1].data.conversation_version == (
            row["conversation_version"] + 1
        ), row["case_id"]


def test_runtime_resolves_controlled_aliases_without_model_product_ids(
    tmp_path: Path,
) -> None:
    message = "帮我对比神仙水和健康水"
    runtime = build_runtime_orchestrator(
        state_dir=tmp_path / "alias-state",
        semantic_intent=MatrixSemanticPort([
            {
                "message": message,
                "translator": {
                    "goal": "comparison",
                    "topic": "skincare",
                    "mention_texts": ["神仙水", "健康水"],
                    "references": [],
                    "question_meaning": "比较两款护肤水",
                    "safety_sensitive": False,
                },
            }
        ]),
    )

    events = list(
        runtime.stream(
            UserTurn(
                session_id="controlled-alias-comparison",
                message=message,
                image_bundle_id=None,
                conversation_version=0,
            )
        )
    )

    assert not any(
        event.event in {"clarify", "error"} for event in events
    )
    intent = next(event for event in events if event.event == "intent")
    assert intent.data.mode == "comparison"
    products = next(
        event for event in events if event.event == "products"
    )
    assert {
        card.product_id for card in products.data.cards
    } == {59, 106}
    evidence = next(
        event
        for event in events
        if event.event == "product_evidence"
    )
    assert set(evidence.data.packet.query.product_ids) == {59, 106}
    assert events[-1].event == "end"


def test_runtime_recognizes_ambiguous_family_but_refuses_default_sku(
    tmp_path: Path,
) -> None:
    message = "B5适合我吗"
    runtime = build_runtime_orchestrator(
        state_dir=tmp_path / "ambiguous-alias-state",
        semantic_intent=MatrixSemanticPort([
            {
                "message": message,
                "translator": {
                    "goal": "suitability",
                    "topic": "skincare",
                    "mention_texts": ["B5"],
                    "references": [],
                    "question_meaning": "询问B5商品适用性",
                    "safety_sensitive": False,
                },
            }
        ]),
    )

    events = list(
        runtime.stream(
            UserTurn(
                session_id="ambiguous-family-alias",
                message=message,
                image_bundle_id=None,
                conversation_version=0,
            )
        )
    )

    clarify = next(
        event for event in events if event.event == "clarify"
    )
    assert clarify.data.clarification_code.value == "reference"
    assert not any(event.event == "products" for event in events)
    assert events[-1].event == "end"
