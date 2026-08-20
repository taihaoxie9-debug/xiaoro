from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from app.guide.retrieval.category_fact_contracts import (
    SourceClass,
    category_field_registry,
)
from app.guide.retrieval.category_profiles import CategoryProfile


_FIELD_ALIASES = {
    "audience": "target_audience",
    "cleansing": "cleansing_requirement",
    "protection_scope": "sun_protection_spectrum",
    "suitable_style": "makeup_style",
    "usage_scenario": "usage_context",
    "variant": "variant_option",
}
_SAFETY_FIELDS = frozenset(
    {
        "ingredients_present",
        "safety",
        "safety_claim",
        "safety_transcript",
    }
)
_NORMALIZED_DICT_TEXT_KEYS = (
    "merchant_claim",
    "instruction",
    "merchant_safety_claim",
    "label_caution",
)


class OcrReviewCurationError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class OcrReviewCurationResult:
    candidates_path: Path
    rejections_path: Path
    accepted_count: int
    rejected_count: int
    rejection_counts: dict[str, int]


@dataclass(frozen=True, slots=True)
class _ReviewDecision:
    action: Literal["safety_transcript", "remap_field"]
    target_field: str | None
    rationale: str


@dataclass(frozen=True, slots=True)
class _ReviewRecovery:
    replacement_display_claim: str
    replacement_normalized_value: str | list[str] | None
    rationale: str


def curate_ocr_review_candidates(
    *,
    source_root: str | Path,
    review_paths: tuple[Path, ...],
    output_root: str | Path,
    product_profiles: dict[int, CategoryProfile],
    decision_path: str | Path | None = None,
    recovery_path: str | Path | None = None,
) -> OcrReviewCurationResult:
    source_directory = Path(source_root)
    destination = Path(output_root)
    if not source_directory.is_dir():
        raise OcrReviewCurationError("OCR source root is unavailable")
    if not review_paths:
        raise OcrReviewCurationError("review candidate inventory is empty")

    definitions = {
        item.key: item for item in category_field_registry().definitions
    }
    source_cache: dict[str, dict[str, object]] = {}
    decisions = _load_decisions(decision_path)
    used_decisions: set[tuple[str, int]] = set()
    recoveries = _load_recoveries(recovery_path)
    used_recoveries: set[tuple[str, int]] = set()
    accepted: list[dict[str, object]] = []
    rejected: list[dict[str, object]] = []
    rejection_counts: Counter[str] = Counter()

    for review_path in sorted(review_paths, key=lambda item: item.name):
        try:
            review_bytes = Path(review_path).read_bytes()
            review_lines = review_bytes.decode("utf-8").splitlines()
        except (OSError, UnicodeDecodeError) as exc:
            raise OcrReviewCurationError(
                "review candidate file is unavailable"
            ) from exc
        review_sha = hashlib.sha256(review_bytes).hexdigest()
        for line_number, line in enumerate(review_lines, start=1):
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise OcrReviewCurationError(
                    f"invalid review JSON line {line_number}"
                ) from exc
            if not isinstance(row, dict):
                raise OcrReviewCurationError(
                    "review candidate must be a JSON object"
                )

            decision_key = (Path(review_path).name, line_number)
            decision = decisions.get(decision_key)
            if decision is not None:
                used_decisions.add(decision_key)
            recovery = recoveries.get(decision_key)
            if recovery is not None:
                used_recoveries.add(decision_key)
            normalized = _normalize_row(
                row=row,
                source_directory=source_directory,
                source_cache=source_cache,
                product_profiles=product_profiles,
                definitions=definitions,
                decision=decision,
                recovery=recovery,
            )
            if isinstance(normalized, str):
                rejection_counts[normalized] += 1
                rejected.append(
                    {
                        "field_key": _required_string(
                            row,
                            ("field_key",),
                            "field key",
                        ),
                        "product_id": _required_product_id(row),
                        "reason": normalized,
                        "source_line": line_number,
                        "source_review_file": Path(review_path).name,
                        "source_review_sha256": review_sha,
                    }
                )
                continue
            accepted.extend(normalized)

    unused_decisions = set(decisions) - used_decisions
    if unused_decisions:
        raise OcrReviewCurationError(
            "review decision does not bind an input row"
        )
    unused_recoveries = set(recoveries) - used_recoveries
    if unused_recoveries:
        raise OcrReviewCurationError(
            "review recovery does not bind an input row"
        )
    accepted = _deduplicate_and_sort(accepted)
    rejected.sort(
        key=lambda item: (
            str(item["source_review_file"]),
            int(item["source_line"]),
            str(item["reason"]),
        )
    )
    candidate_bytes = _jsonl_bytes(accepted)
    rejection_bytes = _jsonl_bytes(rejected)
    candidate_sha = hashlib.sha256(candidate_bytes).hexdigest()
    rejection_sha = hashlib.sha256(rejection_bytes).hexdigest()
    destination.mkdir(parents=True, exist_ok=True)
    candidates_path = (
        destination
        / f"merchant_claim_reviews_v1.{candidate_sha}.jsonl"
    )
    rejections_path = (
        destination
        / f"merchant_claim_review_rejections_v1.{rejection_sha}.jsonl"
    )
    _atomic_write(candidates_path, candidate_bytes)
    _atomic_write(rejections_path, rejection_bytes)
    return OcrReviewCurationResult(
        candidates_path=candidates_path,
        rejections_path=rejections_path,
        accepted_count=len(accepted),
        rejected_count=len(rejected),
        rejection_counts=dict(sorted(rejection_counts.items())),
    )


def _normalize_row(
    *,
    row: dict[str, object],
    source_directory: Path,
    source_cache: dict[str, dict[str, object]],
    product_profiles: dict[int, CategoryProfile],
    definitions: dict[str, object],
    decision: _ReviewDecision | None,
    recovery: _ReviewRecovery | None,
) -> list[dict[str, object]] | str:
    product_id = _required_product_id(row)
    profile = product_profiles.get(product_id)
    if profile is None:
        raise OcrReviewCurationError("unknown canonical product")
    raw_field = _required_string(row, ("field_key",), "field key")
    if decision is not None and decision.action == "remap_field":
        assert decision.target_field is not None
        raw_field = decision.target_field
    raw_scope = row.get("claim_scope", row.get("scope"))
    scope_text = _canonical_json(raw_scope).casefold()
    if "review_transcript" in scope_text:
        return "consumer_review_transcript"
    is_safety = (
        raw_field in _SAFETY_FIELDS
        or "safety" in scope_text
        or (
            decision is not None
            and decision.action == "safety_transcript"
        )
    )

    source_name = _required_string(
        row,
        (
            "source_file",
            "source_json_basename",
            "source",
            "source_basename",
            "source_json",
        ),
        "source file",
    )
    source = _load_source(
        source_directory=source_directory,
        source_name=source_name,
        source_cache=source_cache,
        product_id=product_id,
    )
    image_file = _required_string(
        row,
        ("image_file",),
        "image file",
    )
    display_candidate = (
        recovery.replacement_display_claim
        if recovery is not None
        else _required_string(
            row,
            ("display_claim", "exact_display_claim"),
            "display claim",
        )
    )
    image_index, exact_display = _resolve_exact_display(
        source=source,
        image_file=image_file,
        display_candidate=display_candidate,
        claimed_index=_required_image_index(row),
    )
    if exact_display is None:
        return "display_claim_not_exact"
    if len(exact_display) > 160:
        return "display_claim_too_long"

    rationale = _required_string(
        row,
        ("rationale", "judgment_reason"),
        "rationale",
    )
    if decision is not None:
        rationale = (
            f"{rationale}；主线程裁决：{decision.rationale}"
        )
    if recovery is not None:
        rationale = (
            f"{rationale}；主线程恢复：{recovery.rationale}"
        )
    if len(rationale) > 512:
        return "rationale_too_long"

    if is_safety:
        field_values = (("safety_claim", "商家安全宣称"),)
        claim_scope = "safety_transcript"
    else:
        field_values = _ordinary_field_values(
            raw_field=raw_field,
            normalized_value=(
                recovery.replacement_normalized_value
                if (
                    recovery is not None
                    and recovery.replacement_normalized_value is not None
                )
                else row.get("normalized_value")
            ),
            exact_display=exact_display,
        )
        if field_values is None:
            return "normalized_value_unsupported"
        claim_scope = "ordinary"

    normalized_rows: list[dict[str, object]] = []
    for field_key, normalized_value in field_values:
        if claim_scope == "ordinary":
            definition = definitions.get(field_key)
            if definition is None:
                return "field_not_supported"
            if profile not in definition.profiles:
                return "field_not_applicable"
            policy = next(
                (
                    item
                    for item in definition.source_policies
                    if item.source_class
                    is SourceClass.MERCHANT_DESCRIPTION_OCR
                ),
                None,
            )
            if policy is None or "display" not in policy.capabilities:
                return "field_not_authorized"
        if not normalized_value or len(normalized_value) > 128:
            return "normalized_value_too_long"
        normalized_rows.append(
            {
                "claim_scope": claim_scope,
                "display_claim": exact_display,
                "field_key": field_key,
                "image_file": image_file,
                "image_index": image_index,
                "normalized_value": normalized_value,
                "product_id": product_id,
                "rationale": rationale,
                "source_file": source_name,
            }
        )
    return normalized_rows


def _load_decisions(
    decision_path: str | Path | None,
) -> dict[tuple[str, int], _ReviewDecision]:
    if decision_path is None:
        return {}
    try:
        lines = Path(decision_path).read_text(
            encoding="utf-8"
        ).splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise OcrReviewCurationError(
            "review decision file is unavailable"
        ) from exc
    decisions: dict[tuple[str, int], _ReviewDecision] = {}
    for line_number, line in enumerate(lines, start=1):
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise OcrReviewCurationError(
                f"invalid review decision line {line_number}"
            ) from exc
        if not isinstance(payload, dict) or set(payload) != {
            "source_review_file",
            "source_line",
            "action",
            "target_field",
            "rationale",
        }:
            raise OcrReviewCurationError(
                "review decision contract is invalid"
            )
        source_file = payload["source_review_file"]
        source_line = payload["source_line"]
        action = payload["action"]
        target_field = payload["target_field"]
        rationale = payload["rationale"]
        if (
            not isinstance(source_file, str)
            or Path(source_file).name != source_file
            or not source_file
            or not isinstance(source_line, int)
            or isinstance(source_line, bool)
            or source_line <= 0
            or action not in {"safety_transcript", "remap_field"}
            or not isinstance(rationale, str)
            or not rationale.strip()
        ):
            raise OcrReviewCurationError(
                "review decision values are invalid"
            )
        if action == "safety_transcript":
            if target_field is not None:
                raise OcrReviewCurationError(
                    "safety decision forbids target_field"
                )
        elif (
            not isinstance(target_field, str)
            or not target_field.strip()
        ):
            raise OcrReviewCurationError(
                "field remap requires target_field"
            )
        key = (source_file, source_line)
        if key in decisions:
            raise OcrReviewCurationError(
                "duplicate review decision"
            )
        decisions[key] = _ReviewDecision(
            action=action,
            target_field=(
                target_field.strip()
                if isinstance(target_field, str)
                else None
            ),
            rationale=rationale.strip(),
        )
    return decisions


def _load_recoveries(
    recovery_path: str | Path | None,
) -> dict[tuple[str, int], _ReviewRecovery]:
    if recovery_path is None:
        return {}
    try:
        lines = Path(recovery_path).read_text(
            encoding="utf-8"
        ).splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise OcrReviewCurationError(
            "review recovery file is unavailable"
        ) from exc
    recoveries: dict[tuple[str, int], _ReviewRecovery] = {}
    for line_number, line in enumerate(lines, start=1):
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise OcrReviewCurationError(
                f"invalid review recovery line {line_number}"
            ) from exc
        if not isinstance(payload, dict) or set(payload) != {
            "source_review_file",
            "source_line",
            "replacement_display_claim",
            "replacement_normalized_value",
            "rationale",
        }:
            raise OcrReviewCurationError(
                "review recovery contract is invalid"
            )
        source_file = payload["source_review_file"]
        source_line = payload["source_line"]
        replacement_display = payload["replacement_display_claim"]
        replacement_normalized = payload[
            "replacement_normalized_value"
        ]
        rationale = payload["rationale"]
        normalized_is_valid = (
            replacement_normalized is None
            or (
                isinstance(replacement_normalized, str)
                and bool(replacement_normalized.strip())
            )
            or (
                isinstance(replacement_normalized, list)
                and bool(replacement_normalized)
                and all(
                    isinstance(item, str) and bool(item.strip())
                    for item in replacement_normalized
                )
            )
        )
        if (
            not isinstance(source_file, str)
            or Path(source_file).name != source_file
            or not source_file
            or not isinstance(source_line, int)
            or isinstance(source_line, bool)
            or source_line <= 0
            or not isinstance(replacement_display, str)
            or not replacement_display.strip()
            or not normalized_is_valid
            or not isinstance(rationale, str)
            or not rationale.strip()
        ):
            raise OcrReviewCurationError(
                "review recovery values are invalid"
            )
        key = (source_file, source_line)
        if key in recoveries:
            raise OcrReviewCurationError(
                "duplicate review recovery"
            )
        recoveries[key] = _ReviewRecovery(
            replacement_display_claim=replacement_display.strip(),
            replacement_normalized_value=(
                replacement_normalized.strip()
                if isinstance(replacement_normalized, str)
                else (
                    [
                        item.strip()
                        for item in replacement_normalized
                    ]
                    if isinstance(replacement_normalized, list)
                    else None
                )
            ),
            rationale=rationale.strip(),
        )
    return recoveries


def _ordinary_field_values(
    *,
    raw_field: str,
    normalized_value: object,
    exact_display: str,
) -> tuple[tuple[str, str], ...] | None:
    if raw_field == "fragrance_notes":
        values = _string_values(normalized_value)
        if values is None:
            return None
        mapped: list[tuple[str, str]] = []
        prefixes = {
            "前调：": "top_notes",
            "中调：": "heart_notes",
            "后调：": "base_notes",
        }
        for value in values:
            match = next(
                (
                    (prefix, field_key)
                    for prefix, field_key in prefixes.items()
                    if value.startswith(prefix)
                ),
                None,
            )
            if match is None:
                return None
            prefix, field_key = match
            mapped.append((field_key, value[len(prefix) :].strip()))
        return tuple(mapped)

    field_key = _FIELD_ALIASES.get(raw_field, raw_field)
    values = _string_values(normalized_value)
    if values is None and isinstance(normalized_value, dict):
        values = next(
            (
                (value.strip(),)
                for key in _NORMALIZED_DICT_TEXT_KEYS
                if isinstance(
                    value := normalized_value.get(key),
                    str,
                )
                and value.strip()
            ),
            None,
        )
        if values is None and len(exact_display) <= 128:
            values = (exact_display,)
    if values is None:
        return None
    return tuple((field_key, value) for value in values)


def _string_values(value: object) -> tuple[str, ...] | None:
    if isinstance(value, str) and value.strip():
        return (value.strip(),)
    if (
        isinstance(value, list)
        and value
        and all(isinstance(item, str) and item.strip() for item in value)
    ):
        return tuple(item.strip() for item in value)
    return None


def _load_source(
    *,
    source_directory: Path,
    source_name: str,
    source_cache: dict[str, dict[str, object]],
    product_id: int,
) -> dict[str, object]:
    if Path(source_name).name != source_name:
        raise OcrReviewCurationError(
            "review source must use a basename"
        )
    source = source_cache.get(source_name)
    if source is None:
        try:
            payload = json.loads(
                (source_directory / source_name).read_text(
                    encoding="utf-8"
                )
            )
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise OcrReviewCurationError(
                "review source is unavailable or invalid"
            ) from exc
        if not isinstance(payload, dict):
            raise OcrReviewCurationError(
                "review source must be a JSON object"
            )
        source = payload
        source_cache[source_name] = source
    if source.get("pid") != product_id:
        raise OcrReviewCurationError(
            "review source product binding is invalid"
        )
    if not isinstance(source.get("images"), list):
        raise OcrReviewCurationError(
            "review source images are invalid"
        )
    return source


def _resolve_exact_display(
    *,
    source: dict[str, object],
    image_file: str,
    display_candidate: str,
    claimed_index: int,
) -> tuple[int, str | None]:
    images = source["images"]
    assert isinstance(images, list)
    matches = [
        (index, image)
        for index, image in enumerate(images)
        if (
            isinstance(image, dict)
            and image.get("file") == image_file
            and isinstance(image.get("ocr_text"), str)
        )
    ]
    if not matches:
        raise OcrReviewCurationError(
            "review image file binding is invalid"
        )
    if len(matches) > 1:
        preferred = [
            item
            for item in matches
            if item[0] in {claimed_index, claimed_index - 1}
        ]
        if len(preferred) != 1:
            raise OcrReviewCurationError(
                "review image file binding is ambiguous"
            )
        matches = preferred
    image_index, image = matches[0]
    ocr_text = image["ocr_text"]
    assert isinstance(ocr_text, str)
    return image_index, _recover_exact_source_span(
        ocr_text,
        display_candidate,
    )


def _recover_exact_source_span(
    source_text: str,
    candidate: str,
) -> str | None:
    if candidate in source_text:
        return candidate
    needle = "".join(
        character for character in candidate if not character.isspace()
    )
    indexed = [
        (index, character)
        for index, character in enumerate(source_text)
        if not character.isspace()
    ]
    haystack = "".join(character for _, character in indexed)
    start = haystack.find(needle)
    if not needle or start < 0:
        return None
    source_start = indexed[start][0]
    source_end = indexed[start + len(needle) - 1][0] + 1
    return source_text[source_start:source_end]


def _required_product_id(row: dict[str, object]) -> int:
    value = row.get("product_id", row.get("pid"))
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value <= 0
    ):
        raise OcrReviewCurationError(
            "review product_id must be a positive integer"
        )
    return value


def _required_image_index(row: dict[str, object]) -> int:
    value = row.get("image_index")
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < 0
    ):
        raise OcrReviewCurationError(
            "review image_index must be a non-negative integer"
        )
    return value


def _required_string(
    row: dict[str, object],
    keys: tuple[str, ...],
    label: str,
) -> str:
    value = next(
        (
            candidate
            for key in keys
            if isinstance(candidate := row.get(key), str)
        ),
        None,
    )
    if value is None or not value.strip():
        raise OcrReviewCurationError(
            f"review {label} must be a non-empty string"
        )
    return value.strip()


def _deduplicate_and_sort(
    rows: list[dict[str, object]],
) -> list[dict[str, object]]:
    by_content = {_canonical_json(row): row for row in rows}
    return [by_content[key] for key in sorted(by_content)]


def _jsonl_bytes(rows: list[dict[str, object]]) -> bytes:
    return b"".join(
        (_canonical_json(row) + "\n").encode("utf-8")
        for row in rows
    )


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _atomic_write(path: Path, content: bytes) -> None:
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.",
        dir=path.parent,
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


__all__ = [
    "OcrReviewCurationError",
    "OcrReviewCurationResult",
    "curate_ocr_review_candidates",
]
