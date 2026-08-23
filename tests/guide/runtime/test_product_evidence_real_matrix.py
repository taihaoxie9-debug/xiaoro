from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from app.guide.application.contracts import TurnIdentity, UserTurn
from app.guide.understanding.semantic_contracts import SemanticContext
from app.guide.understanding.turn_meaning_contracts import TurnMeaning
from app.guide_runtime.composition import (
    build_consultation_vertical_runtime,
)


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
    ) -> TurnMeaning:
        del context
        values = self._by_message[message]
        references = tuple(
            {
                "raw_text": item["raw_text"],
                "object_family_hint": "product",
                "ordinal_hint": item["ordinal"],
                "plurality_hint": "single",
            }
            for item in values["references"]
        )
        operation = str(values["goal"])
        return TurnMeaning(
            operation_hint=operation,
            recommendation_mode=(
                "explore" if operation == "recommendation" else None
            ),
            recommendation_count=None,
            recommendation_mode_basis=(
                {
                    "basis": "broad_exploration",
                    "source_text": message,
                }
                if operation == "recommendation"
                else None
            ),
            topic_hint=values["topic"],
            continuity_hint=(
                "continue" if references else "new_task"
            ),
            subject_scope_hint="self",
            reference_mentions=references,
            product_mentions=tuple(
                {"raw_text": text}
                for text in values["mention_texts"]
            ),
            question_meaning=values["question_meaning"],
            safety_language=(
                "safety"
                if values["safety_sensitive"]
                else "ordinary"
            ),
        )


def _presentation_public_text(presentation: object) -> str:
    values: list[str] = []
    for section in presentation.sections:
        for value in (section.copy_text, section.advisor_reason):
            if isinstance(value, str) and value:
                values.append(value)
        values.extend(
            fact.display_value
            for fact in section.direct_facts
        )
    for row in presentation.comparison_rows:
        values.append(row.label)
        values.extend(cell.value for cell in row.cells)
    winner = presentation.winner
    if winner is not None:
        values.extend(
            value
            for value in (winner.reason, winner.tie_reason)
            if isinstance(value, str) and value
        )
    return "\n".join(values)


def _turn(
    *,
    session_id: str,
    message: str,
    version: int,
) -> UserTurn:
    return UserTurn(
        identity=TurnIdentity(
            session_id=session_id,
            request_id=f"request_{session_id}_{version:04d}",
            turn_id=f"turn_{session_id}_{version:04d}",
        ),
        session_id=session_id,
        message=message,
        image_bundle_id=None,
        conversation_version=version,
    )


def _namespace(value):
    if isinstance(value, dict):
        return SimpleNamespace(
            **{key: _namespace(item) for key, item in value.items()}
        )
    if isinstance(value, list):
        return [_namespace(item) for item in value]
    return value


def _decode_events(frames):
    events = []
    for frame in frames:
        lines = frame.decode("utf-8").splitlines()
        name = next(
            line.removeprefix("event: ")
            for line in lines
            if line.startswith("event: ")
        )
        payload = "".join(
            line.removeprefix("data: ")
            for line in lines
            if line.startswith("data: ")
        )
        events.append(
            SimpleNamespace(
                event=name,
                data=_namespace(json.loads(payload)),
            )
        )
    return events


def test_real_question_matrix_closes_production_runtime(
    tmp_path: Path,
) -> None:
    rows = _matrix_rows()
    runtime = build_consultation_vertical_runtime(
        state_dir=tmp_path / "matrix-state",
        semantic_intent=MatrixSemanticPort(rows),
    ).unified

    assert len(rows) == 30
    for row in rows:
        expected = row["expected"]
        events = _decode_events(
            runtime.stream(
                _turn(
                    session_id=row["session_id"],
                    message=row["message"],
                    version=row[
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
        assert intent.data.intent == expected["mode"], row["case_id"]

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

        assert "message" not in event_names, row["case_id"]
        presentations = [
            event.data
            for event in events
            if event.event == "presentation_contract"
        ]
        assert len(presentations) == 1, row["case_id"]
        combined_message = _presentation_public_text(presentations[0])
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
    runtime = build_consultation_vertical_runtime(
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
    ).unified

    events = _decode_events(
        runtime.stream(
            _turn(
                session_id="controlled-alias-comparison",
                message=message,
                version=0,
            )
        )
    )

    assert not any(
        event.event in {"clarify", "error"} for event in events
    )
    intent = next(event for event in events if event.event == "intent")
    assert intent.data.intent == "comparison"
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
    runtime = build_consultation_vertical_runtime(
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
    ).unified

    events = _decode_events(
        runtime.stream(
            _turn(
                session_id="ambiguous-family-alias",
                message=message,
                version=0,
            )
        )
    )

    clarify = next(
        event for event in events if event.event == "clarify"
    )
    assert clarify.data.clarification_code == "reference"
    assert not any(event.event == "products" for event in events)
    assert events[-1].event == "end"
