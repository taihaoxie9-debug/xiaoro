from __future__ import annotations

from collections.abc import Mapping, Sequence
from hashlib import sha256
from pathlib import Path
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from app.guide.adapters.catalog import CanonicalProductReader
from app.guide.presentation.copywriter_contracts import PresentationMode
from tools.guide_gates.continuous_conversation_gate import (
    ContinuousTurnExpectation,
    ContinuousTrajectory,
)
from tools.guide_gates.unified_router_gate import (
    RouteExpectation,
    SemanticExpectation,
)


class MechanicalTruthError(ValueError):
    pass


class _StrictFrozen(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
        protected_namespaces=(),
    )


class ProductFactRequirement(_StrictFrozen):
    product_id: int = Field(gt=0)
    field_keys: tuple[str, ...] = Field(min_length=1)

    @field_validator("field_keys", mode="before")
    @classmethod
    def freeze_field_keys(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value


class TurnTruthRequirement(_StrictFrozen):
    turn_id: str = Field(
        min_length=1,
        max_length=180,
        pattern=r"^[a-z0-9][a-z0-9_-]+$",
    )
    subject_scope_policy: Literal[
        "explicit_self",
        "inherited_self",
    ]
    card_policy: Literal[
        "none",
        "exact_identity",
        "eligible_subset",
    ]
    eligible_product_ids: tuple[int, ...] = ()
    minimum_card_count: int = Field(default=0, ge=0, le=3)
    maximum_card_count: int = Field(default=0, ge=0, le=3)
    fact_requirements: tuple[ProductFactRequirement, ...] = ()

    @field_validator(
        "eligible_product_ids",
        "fact_requirements",
        mode="before",
    )
    @classmethod
    def freeze_sequences(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @model_validator(mode="after")
    def validate_policy(self) -> TurnTruthRequirement:
        if len(self.eligible_product_ids) != len(
            set(self.eligible_product_ids)
        ):
            raise ValueError("eligible product IDs must be unique")
        if self.minimum_card_count > self.maximum_card_count:
            raise ValueError(
                "minimum card count must not exceed maximum"
            )
        if self.card_policy == "none":
            if (
                self.eligible_product_ids
                or self.minimum_card_count
                or self.maximum_card_count
            ):
                raise ValueError(
                    "cardless truth forbids eligible products and counts"
                )
        elif (
            not self.eligible_product_ids
            or self.minimum_card_count == 0
            or self.maximum_card_count == 0
        ):
            raise ValueError(
                "card truth requires eligible products and positive counts"
            )
        return self


class ImageFixtureTruth(_StrictFrozen):
    fixture_id: str = Field(
        min_length=1,
        max_length=160,
        pattern=r"^[a-z0-9][a-z0-9_-]+$",
    )
    product_id: int = Field(gt=0)
    relative_path: str = Field(min_length=1, max_length=512)
    media_type: str = Field(min_length=1, max_length=120)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class RuntimeImageFixture(_StrictFrozen):
    product_id: int = Field(gt=0)
    relative_path: str = Field(min_length=1, max_length=512)
    media_type: str = Field(min_length=1, max_length=120)


class MechanicalTruthSpec(_StrictFrozen):
    schema_version: Literal[
        "guide-continuous-mechanical-truth-v1"
    ] = "guide-continuous-mechanical-truth-v1"
    turns: tuple[TurnTruthRequirement, ...] = Field(min_length=1)
    image_fixtures: tuple[ImageFixtureTruth, ...] = ()

    @field_validator("turns", "image_fixtures", mode="before")
    @classmethod
    def freeze_sequences(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @model_validator(mode="after")
    def validate_unique_ids(self) -> MechanicalTruthSpec:
        turn_ids = tuple(item.turn_id for item in self.turns)
        fixture_ids = tuple(
            item.fixture_id for item in self.image_fixtures
        )
        if len(turn_ids) != len(set(turn_ids)):
            raise ValueError("truth turn IDs must be unique")
        if len(fixture_ids) != len(set(fixture_ids)):
            raise ValueError("image fixture IDs must be unique")
        return self


class MechanicalTruthReport(_StrictFrozen):
    schema_version: Literal[
        "guide-continuous-mechanical-truth-report-v1"
    ] = "guide-continuous-mechanical-truth-report-v1"
    turn_count: int = Field(ge=1)
    canonical_product_count: int = Field(ge=1)
    fact_requirement_count: int = Field(ge=0)
    variable_recommendation_turn_count: int = Field(ge=0)
    image_fixture_count: int = Field(ge=0)


TruthCorrectionIssueCode = Literal[
    "clarification_forbids_presentation_packet",
    "suitability_requires_single_product",
    "explicit_comparison_requires_replace_task",
    "route_continuity_contract",
    "semantic_route_alternative",
    "pending_response_parent_contract",
]


class TurnExpectationCorrection(_StrictFrozen):
    turn_id: str = Field(
        min_length=1,
        max_length=180,
        pattern=r"^[a-z0-9][a-z0-9_-]+$",
    )
    issue_codes: tuple[TruthCorrectionIssueCode, ...] = Field(
        min_length=1,
    )
    acceptable_semantic: SemanticExpectation | None = None
    expected_route: RouteExpectation | None = None
    acceptable_routes: tuple[RouteExpectation, ...] | None = None
    presentation_mode_action: Literal[
        "retain",
        "clear",
        "replace",
    ] = "retain"
    expected_presentation_mode: PresentationMode | None = None

    @field_validator(
        "issue_codes",
        "acceptable_routes",
        mode="before",
    )
    @classmethod
    def freeze_sequences(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @model_validator(mode="after")
    def validate_correction(self) -> TurnExpectationCorrection:
        if len(self.issue_codes) != len(set(self.issue_codes)):
            raise ValueError("correction issue codes must be unique")
        if (
            self.acceptable_routes is not None
            and len(self.acceptable_routes)
            != len(set(self.acceptable_routes))
        ):
            raise ValueError(
                "correction acceptable routes must be unique"
            )
        if (
            self.presentation_mode_action == "replace"
            and self.expected_presentation_mode is None
        ):
            raise ValueError(
                "replacement presentation mode is required"
            )
        if (
            self.presentation_mode_action != "replace"
            and self.expected_presentation_mode is not None
        ):
            raise ValueError(
                "presentation mode is allowed only for replacement"
            )
        if (
            self.acceptable_semantic is None
            and self.expected_route is None
            and self.acceptable_routes is None
            and self.presentation_mode_action == "retain"
        ):
            raise ValueError("correction must change an expectation")
        return self


class TruthCorrectionOverlay(_StrictFrozen):
    schema_version: Literal[
        "guide-continuous-truth-correction-v1"
    ] = "guide-continuous-truth-correction-v1"
    fixture_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    mechanical_truth_sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$"
    )
    corrections: tuple[TurnExpectationCorrection, ...] = Field(
        min_length=1,
    )

    @field_validator("corrections", mode="before")
    @classmethod
    def freeze_corrections(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @model_validator(mode="after")
    def validate_unique_turns(self) -> TruthCorrectionOverlay:
        turn_ids = tuple(
            correction.turn_id for correction in self.corrections
        )
        if len(turn_ids) != len(set(turn_ids)):
            raise ValueError("correction turn IDs must be unique")
        return self


def apply_truth_correction_overlay(
    *,
    trajectories: Sequence[ContinuousTrajectory],
    overlay: TruthCorrectionOverlay,
    fixture_path: str | Path,
    manifest_path: str | Path,
    mechanical_truth_path: str | Path,
) -> tuple[ContinuousTrajectory, ...]:
    normalized = tuple(trajectories)
    if (
        not normalized
        or any(
            type(item) is not ContinuousTrajectory
            for item in normalized
        )
    ):
        raise TypeError(
            "trajectories must contain ContinuousTrajectory values"
        )
    if type(overlay) is not TruthCorrectionOverlay:
        raise TypeError(
            "overlay must be an exact TruthCorrectionOverlay"
        )
    source_hashes = (
        _file_sha256(fixture_path),
        _file_sha256(manifest_path),
        _file_sha256(mechanical_truth_path),
    )
    expected_hashes = (
        overlay.fixture_sha256,
        overlay.manifest_sha256,
        overlay.mechanical_truth_sha256,
    )
    if source_hashes != expected_hashes:
        raise MechanicalTruthError(
            "truth_correction_source_hash_mismatch"
        )
    corrections_by_id = {
        correction.turn_id: correction
        for correction in overlay.corrections
    }
    paper_turn_ids = {
        turn.turn_id
        for trajectory in normalized
        for turn in trajectory.turns
    }
    unknown_turn_ids = set(corrections_by_id).difference(
        paper_turn_ids
    )
    if unknown_turn_ids:
        raise MechanicalTruthError(
            "truth_correction_unknown_turn:"
            + ",".join(sorted(unknown_turn_ids))
        )

    corrected_trajectories: list[ContinuousTrajectory] = []
    for trajectory in normalized:
        corrected_turns = tuple(
            _apply_turn_correction(
                turn,
                correction=corrections_by_id.get(turn.turn_id),
            )
            for turn in trajectory.turns
        )
        payload = trajectory.model_dump(mode="python")
        payload["turns"] = corrected_turns
        corrected_trajectories.append(
            ContinuousTrajectory.model_validate(
                payload,
                strict=True,
            )
        )
    return tuple(corrected_trajectories)


def audit_mechanical_truth(
    *,
    trajectories: Sequence[ContinuousTrajectory],
    canonical_reader: CanonicalProductReader,
    spec: MechanicalTruthSpec,
    runtime_image_fixtures: Mapping[str, RuntimeImageFixture],
    repo_root: str | Path,
) -> MechanicalTruthReport:
    normalized = tuple(trajectories)
    if (
        not normalized
        or any(
            type(item) is not ContinuousTrajectory
            for item in normalized
        )
    ):
        raise TypeError(
            "trajectories must contain ContinuousTrajectory values"
        )
    if type(canonical_reader) is not CanonicalProductReader:
        raise TypeError(
            "canonical_reader must be an exact CanonicalProductReader"
        )
    if type(spec) is not MechanicalTruthSpec:
        raise TypeError("spec must be an exact MechanicalTruthSpec")
    root = Path(repo_root).resolve()
    turns = tuple(
        turn
        for trajectory in normalized
        for turn in trajectory.turns
    )
    turn_ids = tuple(turn.turn_id for turn in turns)
    if len(turn_ids) != len(set(turn_ids)):
        raise MechanicalTruthError("duplicate_turn_id")
    truth_by_id = {item.turn_id: item for item in spec.turns}
    if set(truth_by_id) != set(turn_ids):
        raise MechanicalTruthError("truth_turn_coverage_mismatch")
    previous_turn_by_id = {
        turn.turn_id: (
            trajectory.turns[index - 1]
            if index > 0
            else None
        )
        for trajectory in normalized
        for index, turn in enumerate(trajectory.turns)
    }

    canonical_ids = canonical_reader.product_ids
    referenced_ids = {
        product_id
        for turn in turns
        for product_id in (
            *turn.expected_card_ids,
            *(
                binding.product_id
                for binding in turn.expected_bindings
            ),
            *_nested_product_ids(turn.expected_snapshot_subset),
            *_nested_product_ids(turn.expected_task_plan_subset),
        )
    }
    _require_known_products(
        referenced_ids,
        canonical_ids=canonical_ids,
    )

    fact_requirement_count = 0
    variable_recommendation_turn_count = 0
    for turn in turns:
        truth = truth_by_id[turn.turn_id]
        _require_known_products(
            truth.eligible_product_ids,
            canonical_ids=canonical_ids,
        )
        _validate_scope(turn, truth)
        _validate_card_policy(turn, truth)
        _validate_presentation_policy(turn)
        _validate_route_policy(
            turn,
            previous_turn=previous_turn_by_id[turn.turn_id],
        )
        if truth.card_policy == "eligible_subset":
            variable_recommendation_turn_count += 1
        for requirement in truth.fact_requirements:
            fact_requirement_count += len(requirement.field_keys)
            _validate_fact_requirement(
                canonical_reader=canonical_reader,
                requirement=requirement,
            )

    used_fixture_ids = {
        fixture_id
        for turn in turns
        for fixture_id in turn.image_fixture_ids
    }
    fixture_truth_by_id = {
        item.fixture_id: item for item in spec.image_fixtures
    }
    if set(fixture_truth_by_id) != used_fixture_ids:
        raise MechanicalTruthError("image_fixture_coverage_mismatch")
    for fixture_id in sorted(used_fixture_ids):
        _validate_image_fixture(
            fixture_truth_by_id[fixture_id],
            runtime=runtime_image_fixtures.get(fixture_id),
            canonical_ids=canonical_ids,
            repo_root=root,
        )

    return MechanicalTruthReport(
        turn_count=len(turns),
        canonical_product_count=len(canonical_reader),
        fact_requirement_count=fact_requirement_count,
        variable_recommendation_turn_count=(
            variable_recommendation_turn_count
        ),
        image_fixture_count=len(used_fixture_ids),
    )


def _require_known_products(
    product_ids: Sequence[int] | set[int],
    *,
    canonical_ids: frozenset[int],
) -> None:
    unknown = set(product_ids).difference(canonical_ids)
    if unknown:
        raise MechanicalTruthError(
            "unknown_product:"
            + ",".join(str(value) for value in sorted(unknown))
        )


def _validate_scope(turn, truth: TurnTruthRequirement) -> None:
    scopes = set(turn.acceptable_semantic.subject_scope_hints)
    if "other" in scopes:
        raise MechanicalTruthError("self_only_scope_allows_other")
    if truth.subject_scope_policy == "explicit_self":
        if scopes != {"self"}:
            raise MechanicalTruthError(
                "explicit_scope_not_self_only"
            )
        return
    if not {"self", "unknown"}.issubset(scopes):
        raise MechanicalTruthError(
            "inherited_scope_rejects_unknown"
        )


def _validate_card_policy(
    turn,
    truth: TurnTruthRequirement,
) -> None:
    expected_ids = tuple(turn.expected_card_ids)
    if truth.card_policy == "none":
        if expected_ids:
            raise MechanicalTruthError("cardless_turn_has_cards")
        return
    if truth.card_policy == "exact_identity":
        if set(expected_ids) != set(truth.eligible_product_ids):
            raise MechanicalTruthError(
                "exact_identity_card_mismatch"
            )
        if not (
            truth.minimum_card_count
            <= len(expected_ids)
            <= truth.maximum_card_count
        ):
            raise MechanicalTruthError(
                "exact_identity_card_count_mismatch"
            )
        return
    if expected_ids:
        raise MechanicalTruthError(
            "variable_recommendation_fixed_cards"
        )
    if (
        turn.expected_route.processor != "recommendation"
        or turn.public_answer_policy != "recommendation"
    ):
        raise MechanicalTruthError(
            "eligible_subset_requires_recommendation"
        )


def _validate_presentation_policy(
    turn: ContinuousTurnExpectation,
) -> None:
    if (
        turn.expected_clarification
        and turn.expected_presentation_mode is not None
    ):
        raise MechanicalTruthError(
            "clarification_forbids_presentation_packet"
        )
    if (
        turn.expected_task_plan_subset.get("mode")
        == "suitability"
        and turn.expected_presentation_mode != "single_product"
    ):
        raise MechanicalTruthError(
            "suitability_requires_single_product"
        )


def _validate_route_policy(
    turn: ContinuousTurnExpectation,
    *,
    previous_turn: ContinuousTurnExpectation | None,
) -> None:
    if (
        turn.expected_route.processor != "comparison"
        or turn.expected_route.focus_source != "explicit_product"
        or len(turn.expected_bindings) < 2
    ):
        return
    previous_processor = _expected_active_processor(previous_turn)
    if previous_processor != "comparison":
        for route in (
            turn.expected_route,
            *turn.acceptable_routes,
        ):
            if route.continuity != "replace_task":
                raise MechanicalTruthError(
                    "explicit_comparison_requires_replace_task"
                )


def _expected_active_processor(
    turn: ContinuousTurnExpectation | None,
) -> str | None:
    if turn is None:
        return None
    focus_state = turn.expected_snapshot_subset.get("focus_state")
    if isinstance(focus_state, dict):
        active_processor = focus_state.get("active_processor")
        if isinstance(active_processor, str):
            return active_processor
    return turn.expected_route.processor


def _apply_turn_correction(
    turn: ContinuousTurnExpectation,
    *,
    correction: TurnExpectationCorrection | None,
) -> ContinuousTurnExpectation:
    if correction is None:
        return turn
    payload = turn.model_dump(mode="python")
    if correction.acceptable_semantic is not None:
        payload["acceptable_semantic"] = (
            correction.acceptable_semantic
        )
    if correction.expected_route is not None:
        payload["expected_route"] = correction.expected_route
    if correction.acceptable_routes is not None:
        payload["acceptable_routes"] = correction.acceptable_routes
    if correction.presentation_mode_action == "clear":
        payload["expected_presentation_mode"] = None
    elif correction.presentation_mode_action == "replace":
        payload["expected_presentation_mode"] = (
            correction.expected_presentation_mode
        )
    return ContinuousTurnExpectation.model_validate(
        payload,
        strict=True,
    )


def _file_sha256(path: str | Path) -> str:
    try:
        return sha256(Path(path).read_bytes()).hexdigest()
    except OSError as exc:
        raise MechanicalTruthError(
            "truth_correction_source_unreadable"
        ) from exc


def _validate_fact_requirement(
    *,
    canonical_reader: CanonicalProductReader,
    requirement: ProductFactRequirement,
) -> None:
    if requirement.product_id not in canonical_reader.product_ids:
        raise MechanicalTruthError(
            f"unknown_product:{requirement.product_id}"
        )
    product = canonical_reader.get(requirement.product_id)
    for field_key in requirement.field_keys:
        field = product.fields.get(field_key)
        if (
            field is None
            or field.resolved_state != "known"
            or not field.source_refs
        ):
            raise MechanicalTruthError(
                "field_not_known:"
                f"{requirement.product_id}:{field_key}"
            )


def _validate_image_fixture(
    truth: ImageFixtureTruth,
    *,
    runtime: RuntimeImageFixture | None,
    canonical_ids: frozenset[int],
    repo_root: Path,
) -> None:
    if truth.product_id not in canonical_ids:
        raise MechanicalTruthError(
            f"unknown_product:{truth.product_id}"
        )
    if (
        runtime is None
        or runtime.product_id != truth.product_id
        or runtime.relative_path != truth.relative_path
        or runtime.media_type != truth.media_type
    ):
        raise MechanicalTruthError("image_fixture_mismatch")
    relative_path = Path(truth.relative_path)
    if relative_path.is_absolute():
        raise MechanicalTruthError("image_fixture_mismatch")
    path = (repo_root / relative_path).resolve()
    try:
        path.relative_to(repo_root)
        digest = sha256(path.read_bytes()).hexdigest()
    except (OSError, ValueError) as exc:
        raise MechanicalTruthError(
            "image_fixture_mismatch"
        ) from exc
    if digest != truth.sha256:
        raise MechanicalTruthError("image_fixture_mismatch")


def _nested_product_ids(value: object) -> tuple[int, ...]:
    collected: list[int] = []

    def collect(item: object, key: str | None = None) -> None:
        if isinstance(item, dict):
            for child_key, child in item.items():
                collect(child, str(child_key))
            return
        if isinstance(item, (list, tuple)):
            if key is not None and key.endswith("product_ids"):
                collected.extend(
                    child
                    for child in item
                    if isinstance(child, int)
                    and not isinstance(child, bool)
                )
                return
            for child in item:
                collect(child, key)
            return
        if (
            key is not None
            and (
                key == "product_id"
                or key.endswith("_product_id")
            )
            and isinstance(item, int)
            and not isinstance(item, bool)
        ):
            collected.append(item)

    collect(value)
    return tuple(collected)


__all__ = [
    "ImageFixtureTruth",
    "MechanicalTruthError",
    "MechanicalTruthReport",
    "MechanicalTruthSpec",
    "ProductFactRequirement",
    "RuntimeImageFixture",
    "TruthCorrectionOverlay",
    "TurnExpectationCorrection",
    "TurnTruthRequirement",
    "apply_truth_correction_overlay",
    "audit_mechanical_truth",
]
