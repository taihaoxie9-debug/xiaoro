from __future__ import annotations

from pathlib import Path

import pytest

from app.guide.adapters.catalog import CanonicalProductReader
from app.guide.retrieval.product_name_resolver import (
    ResolvedProductBinding,
)
from tools.guide_gates.continuous_conversation_gate import (
    ContinuousTrajectory,
)
from tools.guide_gates.continuous_conversation_mechanical_truth import (
    ImageFixtureTruth,
    MechanicalTruthError,
    MechanicalTruthSpec,
    ProductFactRequirement,
    RuntimeImageFixture,
    TruthCorrectionOverlay,
    TurnExpectationCorrection,
    TurnTruthRequirement,
    apply_truth_correction_overlay,
    audit_mechanical_truth,
)
from tools.guide_gates.continuous_conversation_runtime import (
    runtime_image_fixtures,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
CANONICAL_ROOT = REPO_ROOT / "data" / "canonical"
IMAGE_PATH = (
    "app/static/images/products/taobao_v3_572910260362.png"
)
IMAGE_SHA256 = (
    "56c5c1dd36143968b2781eac3582dc99"
    "b7b4754b599077c527797c85d508adb9"
)


def _reader() -> CanonicalProductReader:
    return CanonicalProductReader.from_files(
        manifest_path=(
            CANONICAL_ROOT / "core_products_v1_manifest.json"
        ),
        products_path=CANONICAL_ROOT / "core_products_v1.jsonl",
    )


def _trajectory() -> ContinuousTrajectory:
    turns = (
        _turn(
            "truth-t1",
            processor="recommendation",
            presentation_mode="recommendation",
            public_answer_policy="recommendation",
        ),
        _turn(
            "truth-t2",
            processor="product_knowledge",
            focus_source="explicit_product",
            presentation_mode="product_knowledge",
            public_answer_policy="product_knowledge",
            expected_bindings=(
                ResolvedProductBinding(
                    product_id=38,
                    source_text="explicit",
                ),
            ),
            expected_card_ids=(38,),
        ),
        _turn(
            "truth-t3",
            processor="general_knowledge",
            focus_source="knowledge_topic",
            presentation_mode="general_knowledge",
            public_answer_policy="general_knowledge",
        ),
        _turn(
            "truth-t4",
            processor="image_identity",
            focus_source="confirmed_image",
            presentation_mode="image_identity",
            public_answer_policy="product_knowledge",
            image_fixture_ids=("product-53-front",),
            expected_bindings=(
                ResolvedProductBinding(
                    product_id=53,
                    source_text="image",
                ),
            ),
            expected_card_ids=(53,),
        ),
        _turn(
            "truth-t5",
            processor="clarification",
            presentation_mode=None,
            public_answer_policy="clarification",
            expected_clarification=True,
        ),
    )
    return ContinuousTrajectory(
        trajectory_id="truth",
        subject_scope="self",
        route_families=("truth",),
        turns=turns,
    )


def _turn(
    turn_id: str,
    *,
    processor: str,
    focus_source: str = "none",
    presentation_mode: str | None,
    public_answer_policy: str,
    image_fixture_ids: tuple[str, ...] = (),
    expected_bindings: tuple[ResolvedProductBinding, ...] = (),
    expected_card_ids: tuple[int, ...] = (),
    expected_clarification: bool = False,
):
    return {
        "turn_id": turn_id,
        "message": f"message for {turn_id}",
        "image_fixture_ids": image_fixture_ids,
        "acceptable_semantic": {
            "operation_hints": (
                "clarification"
                if processor == "clarification"
                else "knowledge"
                if processor
                in {"product_knowledge", "general_knowledge"}
                else "image_identity"
                if processor == "image_identity"
                else "recommendation",
            ),
            "topic_hints": ("serum",),
            "continuity_hints": ("continue",),
            "subject_scope_hints": ("self", "unknown"),
        },
        "expected_bindings": expected_bindings,
        "expected_route": {
            "processor": processor,
            "continuity": "continue",
            "focus_source": focus_source,
        },
        "expected_snapshot_subset": {},
        "expected_task_plan_subset": {},
        "expected_card_ids": expected_card_ids,
        "expected_safety": False,
        "expected_clarification": expected_clarification,
        "expected_presentation_mode": presentation_mode,
        "public_answer_policy": public_answer_policy,
    }


def _spec(
    *,
    overrides: dict[str, TurnTruthRequirement] | None = None,
) -> MechanicalTruthSpec:
    turns = {
        "truth-t1": TurnTruthRequirement(
            turn_id="truth-t1",
            subject_scope_policy="inherited_self",
            card_policy="eligible_subset",
            eligible_product_ids=(38, 91),
            minimum_card_count=1,
            maximum_card_count=3,
            fact_requirements=(
                ProductFactRequirement(
                    product_id=38,
                    field_keys=("price", "efficacy"),
                ),
            ),
        ),
        "truth-t2": TurnTruthRequirement(
            turn_id="truth-t2",
            subject_scope_policy="inherited_self",
            card_policy="exact_identity",
            eligible_product_ids=(38,),
            minimum_card_count=1,
            maximum_card_count=1,
        ),
        "truth-t3": TurnTruthRequirement(
            turn_id="truth-t3",
            subject_scope_policy="inherited_self",
            card_policy="none",
        ),
        "truth-t4": TurnTruthRequirement(
            turn_id="truth-t4",
            subject_scope_policy="inherited_self",
            card_policy="exact_identity",
            eligible_product_ids=(53,),
            minimum_card_count=1,
            maximum_card_count=1,
        ),
        "truth-t5": TurnTruthRequirement(
            turn_id="truth-t5",
            subject_scope_policy="inherited_self",
            card_policy="none",
        ),
    }
    turns.update(overrides or {})
    return MechanicalTruthSpec(
        turns=tuple(turns.values()),
        image_fixtures=(
            ImageFixtureTruth(
                fixture_id="product-53-front",
                product_id=53,
                relative_path=IMAGE_PATH,
                media_type="image/png",
                sha256=IMAGE_SHA256,
            ),
        ),
    )


def _runtime_images() -> dict[str, RuntimeImageFixture]:
    return {
        "product-53-front": RuntimeImageFixture(
            product_id=53,
            relative_path=IMAGE_PATH,
            media_type="image/png",
        )
    }


def _audit(
    spec: MechanicalTruthSpec,
    *,
    trajectory: ContinuousTrajectory | None = None,
):
    return audit_mechanical_truth(
        trajectories=(trajectory or _trajectory(),),
        canonical_reader=_reader(),
        spec=spec,
        runtime_image_fixtures=_runtime_images(),
        repo_root=REPO_ROOT,
    )


def test_mechanical_truth_accepts_grounded_fixture() -> None:
    report = _audit(_spec())

    assert report.turn_count == 5
    assert report.canonical_product_count == 103
    assert report.fact_requirement_count == 2
    assert report.variable_recommendation_turn_count == 1
    assert report.image_fixture_count == 1


def test_mechanical_truth_rejects_unknown_product() -> None:
    with pytest.raises(
        MechanicalTruthError,
        match="unknown_product",
    ):
        _audit(
            _spec(
                overrides={
                    "truth-t3": TurnTruthRequirement(
                        turn_id="truth-t3",
                        subject_scope_policy="inherited_self",
                        card_policy="none",
                        fact_requirements=(
                            ProductFactRequirement(
                                product_id=999999,
                                field_keys=("price",),
                            ),
                        ),
                    )
                }
            )
        )


def test_mechanical_truth_rejects_unknown_canonical_field() -> None:
    with pytest.raises(
        MechanicalTruthError,
        match="field_not_known",
    ):
        _audit(
            _spec(
                overrides={
                    "truth-t3": TurnTruthRequirement(
                        turn_id="truth-t3",
                        subject_scope_policy="inherited_self",
                        card_policy="none",
                        fact_requirements=(
                            ProductFactRequirement(
                                product_id=24,
                                field_keys=("ingredients_present",),
                            ),
                        ),
                    )
                }
            )
        )


def test_variable_recommendation_forbids_fixed_top_k() -> None:
    trajectory = _trajectory()
    first = trajectory.turns[0].model_copy(
        update={"expected_card_ids": (38, 91)},
        deep=True,
    )
    trajectory = trajectory.model_copy(
        update={"turns": (first, *trajectory.turns[1:])},
        deep=True,
    )

    with pytest.raises(
        MechanicalTruthError,
        match="variable_recommendation_fixed_cards",
    ):
        _audit(_spec(), trajectory=trajectory)


def test_inherited_self_scope_accepts_unknown() -> None:
    trajectory = _trajectory()
    first = trajectory.turns[0].model_copy(
        update={
            "acceptable_semantic": (
                trajectory.turns[0].acceptable_semantic.model_copy(
                    update={"subject_scope_hints": ("self",)},
                    deep=True,
                )
            )
        },
        deep=True,
    )
    trajectory = trajectory.model_copy(
        update={"turns": (first, *trajectory.turns[1:])},
        deep=True,
    )

    with pytest.raises(
        MechanicalTruthError,
        match="inherited_scope_rejects_unknown",
    ):
        _audit(_spec(), trajectory=trajectory)


def test_clarification_forbids_presentation_packet_expectation() -> None:
    trajectory = _trajectory()
    clarification = trajectory.turns[4].model_copy(
        update={"expected_presentation_mode": "clarification"},
        deep=True,
    )
    trajectory = trajectory.model_copy(
        update={"turns": (*trajectory.turns[:4], clarification)},
        deep=True,
    )

    with pytest.raises(
        MechanicalTruthError,
        match="clarification_forbids_presentation_packet",
    ):
        _audit(_spec(), trajectory=trajectory)


def test_suitability_requires_single_product_presentation() -> None:
    trajectory = _trajectory()
    suitability = trajectory.turns[1].model_copy(
        update={
            "expected_task_plan_subset": {"mode": "suitability"},
            "expected_presentation_mode": "product_knowledge",
        },
        deep=True,
    )
    trajectory = trajectory.model_copy(
        update={
            "turns": (
                trajectory.turns[0],
                suitability,
                *trajectory.turns[2:],
            )
        },
        deep=True,
    )

    with pytest.raises(
        MechanicalTruthError,
        match="suitability_requires_single_product",
    ):
        _audit(_spec(), trajectory=trajectory)


def test_explicit_comparison_from_noncomparison_requires_replace_task(
) -> None:
    trajectory = _trajectory()
    comparison = trajectory.turns[1].model_copy(
        update={
            "expected_bindings": (
                ResolvedProductBinding(
                    product_id=38,
                    source_text="explicit-a",
                ),
                ResolvedProductBinding(
                    product_id=91,
                    source_text="explicit-b",
                ),
            ),
            "expected_route": (
                trajectory.turns[1].expected_route.model_copy(
                    update={
                        "processor": "comparison",
                        "continuity": "continue",
                        "focus_source": "explicit_product",
                    }
                )
            ),
            "expected_card_ids": (38, 91),
            "expected_presentation_mode": "comparison",
            "public_answer_policy": "comparison",
        },
        deep=True,
    )
    trajectory = trajectory.model_copy(
        update={
            "turns": (
                trajectory.turns[0],
                comparison,
                *trajectory.turns[2:],
            )
        },
        deep=True,
    )
    spec = _spec(
        overrides={
            "truth-t2": TurnTruthRequirement(
                turn_id="truth-t2",
                subject_scope_policy="inherited_self",
                card_policy="exact_identity",
                eligible_product_ids=(38, 91),
                minimum_card_count=2,
                maximum_card_count=2,
            )
        }
    )

    with pytest.raises(
        MechanicalTruthError,
        match="explicit_comparison_requires_replace_task",
    ):
        _audit(spec, trajectory=trajectory)


def test_truth_correction_overlay_updates_only_authoring_expectations(
    tmp_path: Path,
) -> None:
    fixture = tmp_path / "paper.jsonl"
    manifest = tmp_path / "paper_manifest.json"
    truth = tmp_path / "paper_truth.json"
    fixture.write_bytes(b"sealed fixture\n")
    manifest.write_bytes(b"sealed manifest\n")
    truth.write_bytes(b"sealed truth\n")
    trajectory = _trajectory()
    alternative = trajectory.turns[1].expected_route.model_copy(
        update={"continuity": "replace_task"},
        deep=True,
    )
    overlay = TruthCorrectionOverlay(
        fixture_sha256=_sha256(fixture),
        manifest_sha256=_sha256(manifest),
        mechanical_truth_sha256=_sha256(truth),
        corrections=(
            TurnExpectationCorrection(
                turn_id="truth-t2",
                issue_codes=(
                    "semantic_route_alternative",
                    "suitability_requires_single_product",
                ),
                acceptable_routes=(alternative,),
                presentation_mode_action="replace",
                expected_presentation_mode="single_product",
            ),
            TurnExpectationCorrection(
                turn_id="truth-t5",
                issue_codes=(
                    "clarification_forbids_presentation_packet",
                ),
                presentation_mode_action="clear",
            ),
        ),
    )

    corrected = apply_truth_correction_overlay(
        trajectories=(trajectory,),
        overlay=overlay,
        fixture_path=fixture,
        manifest_path=manifest,
        mechanical_truth_path=truth,
    )

    assert corrected[0] is not trajectory
    assert trajectory.turns[1].acceptable_routes == ()
    assert corrected[0].turns[1].acceptable_routes == (
        alternative,
    )
    assert (
        corrected[0].turns[1].expected_presentation_mode
        == "single_product"
    )
    assert corrected[0].turns[4].expected_presentation_mode is None
    assert corrected[0].turns[1].message == trajectory.turns[1].message
    assert (
        corrected[0].turns[1].expected_bindings
        == trajectory.turns[1].expected_bindings
    )


def test_truth_correction_overlay_rejects_source_hash_drift(
    tmp_path: Path,
) -> None:
    fixture = tmp_path / "paper.jsonl"
    manifest = tmp_path / "paper_manifest.json"
    truth = tmp_path / "paper_truth.json"
    fixture.write_bytes(b"sealed fixture\n")
    manifest.write_bytes(b"sealed manifest\n")
    truth.write_bytes(b"sealed truth\n")
    overlay = TruthCorrectionOverlay(
        fixture_sha256="0" * 64,
        manifest_sha256=_sha256(manifest),
        mechanical_truth_sha256=_sha256(truth),
        corrections=(
            TurnExpectationCorrection(
                turn_id="truth-t5",
                issue_codes=(
                    "clarification_forbids_presentation_packet",
                ),
                presentation_mode_action="clear",
            ),
        ),
    )

    with pytest.raises(
        MechanicalTruthError,
        match="truth_correction_source_hash_mismatch",
    ):
        apply_truth_correction_overlay(
            trajectories=(_trajectory(),),
            overlay=overlay,
            fixture_path=fixture,
            manifest_path=manifest,
            mechanical_truth_path=truth,
        )


def test_truth_correction_overlay_can_replace_typed_semantic_truth(
    tmp_path: Path,
) -> None:
    fixture = tmp_path / "paper.jsonl"
    manifest = tmp_path / "paper_manifest.json"
    truth = tmp_path / "paper_truth.json"
    fixture.write_bytes(b"sealed fixture\n")
    manifest.write_bytes(b"sealed manifest\n")
    truth.write_bytes(b"sealed truth\n")
    trajectory = _trajectory()
    corrected_semantic = (
        trajectory.turns[0].acceptable_semantic.model_copy(
            update={
                "operation_hints": (
                    "recommendation",
                    "followup",
                )
            },
            deep=True,
        )
    )
    overlay = TruthCorrectionOverlay(
        fixture_sha256=_sha256(fixture),
        manifest_sha256=_sha256(manifest),
        mechanical_truth_sha256=_sha256(truth),
        corrections=(
            TurnExpectationCorrection(
                turn_id="truth-t1",
                issue_codes=(
                    "pending_response_parent_contract",
                ),
                acceptable_semantic=corrected_semantic,
            ),
        ),
    )

    corrected = apply_truth_correction_overlay(
        trajectories=(trajectory,),
        overlay=overlay,
        fixture_path=fixture,
        manifest_path=manifest,
        mechanical_truth_path=truth,
    )

    assert (
        trajectory.turns[0].acceptable_semantic.operation_hints
        == ("recommendation",)
    )
    assert (
        corrected[0].turns[0].acceptable_semantic
        == corrected_semantic
    )
    assert corrected[0].turns[0].message == trajectory.turns[0].message


def test_image_fixture_must_match_runtime_binding_and_hash() -> None:
    bad = _spec().model_copy(
        update={
            "image_fixtures": (
                ImageFixtureTruth(
                    fixture_id="product-53-front",
                    product_id=55,
                    relative_path=IMAGE_PATH,
                    media_type="image/png",
                    sha256="0" * 64,
                ),
            )
        },
        deep=True,
    )

    with pytest.raises(
        MechanicalTruthError,
        match="image_fixture_mismatch",
    ):
        _audit(bad)


def test_runtime_image_fixtures_bind_identity_explicitly() -> None:
    fixtures = runtime_image_fixtures()

    assert fixtures["product-53-front"] == RuntimeImageFixture(
        product_id=53,
        relative_path=IMAGE_PATH,
        media_type="image/png",
    )
    assert fixtures["product-55-front"].product_id == 55


def _sha256(path: Path) -> str:
    from hashlib import sha256

    return sha256(path.read_bytes()).hexdigest()
