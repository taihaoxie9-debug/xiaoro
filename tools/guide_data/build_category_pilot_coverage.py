"""Build the deterministic coverage report for the twelve category pilots."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import tempfile
from typing import Sequence

from app.guide.adapters.catalog.canonical_product_reader import (
    CanonicalProductReader,
)
from app.guide.retrieval.category_fact_assets import (
    ApprovedCategoryFact,
    load_category_fact_assets,
)
from app.guide.retrieval.category_fact_contracts import (
    SourceClass,
    category_field_registry,
)
from app.guide.retrieval.category_profiles import CategoryProfile


@dataclass(frozen=True, slots=True)
class PilotCoverageRow:
    category_profile: CategoryProfile
    product_id: int
    applicable_fields: tuple[str, ...]
    approved_known_fields: tuple[str, ...]
    unknown_fields: tuple[str, ...]
    conflict_fields: tuple[str, ...]
    source_refs: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ProfileCoverageStats:
    category_profile: CategoryProfile
    pilot_count: int
    approved: int
    unknown: int
    conflict: int


@dataclass(frozen=True, slots=True)
class PilotCoverageReport:
    rows: tuple[PilotCoverageRow, ...]
    profile_stats: tuple[ProfileCoverageStats, ...]

    def stats_for(
        self,
        profile: CategoryProfile,
    ) -> ProfileCoverageStats:
        return next(
            stats
            for stats in self.profile_stats
            if stats.category_profile is profile
        )


def build_category_pilot_coverage(
    *,
    manifest_path: str | Path,
    canonical_manifest_path: str | Path,
    canonical_products_path: str | Path,
    report_path: str | Path,
    facts_path: str | Path | None = None,
) -> PilotCoverageReport:
    canonical_reader = CanonicalProductReader.from_files(
        manifest_path=canonical_manifest_path,
        products_path=canonical_products_path,
    )
    assets = load_category_fact_assets(
        manifest_path=manifest_path,
        facts_path=facts_path,
        canonical_reader=canonical_reader,
        field_registry=category_field_registry(),
    )
    facts_by_field: dict[
        tuple[int, str],
        list[ApprovedCategoryFact],
    ] = {}
    for fact in assets.facts:
        facts_by_field.setdefault(
            (fact.product_id, fact.field_key),
            [],
        ).append(fact)

    rows = tuple(
        _build_row(
            category_profile=binding.category_profile,
            product_id=binding.product_id,
            facts_by_field=facts_by_field,
        )
        for binding in assets.manifest.pilot_bindings
    )
    profile_stats = tuple(
        _build_profile_stats(profile=profile, rows=rows)
        for profile in CategoryProfile
    )
    report = PilotCoverageReport(
        rows=rows,
        profile_stats=profile_stats,
    )
    report_bytes = _render_markdown(
        report,
        facts_file=assets.manifest.facts_file,
        facts_sha256=assets.manifest.facts_sha256,
        fact_count=assets.manifest.fact_count,
    ).encode("utf-8")
    _write_atomically(Path(report_path), report_bytes)
    return report


def _build_row(
    *,
    category_profile: CategoryProfile,
    product_id: int,
    facts_by_field: dict[
        tuple[int, str],
        list[ApprovedCategoryFact],
    ],
) -> PilotCoverageRow:
    applicable_fields = tuple(
        sorted(
            definition.key
            for definition in category_field_registry().for_profile(
                category_profile
            )
            if any(
                policy.source_class is not SourceClass.CANONICAL_CORE
                for policy in definition.source_policies
            )
        )
    )
    approved: list[str] = []
    unknown: list[str] = []
    conflicts: list[str] = []
    source_refs: set[str] = set()
    for field_key in applicable_fields:
        facts = facts_by_field.get((product_id, field_key), [])
        if not facts:
            unknown.append(field_key)
            continue
        source_refs.update(
            reference
            for fact in facts
            for reference in fact.source_refs
        )
        values = {
            json.dumps(
                fact.value,
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            for fact in facts
        }
        if len(values) == 1:
            approved.append(field_key)
        else:
            conflicts.append(field_key)
    return PilotCoverageRow(
        category_profile=category_profile,
        product_id=product_id,
        applicable_fields=applicable_fields,
        approved_known_fields=tuple(approved),
        unknown_fields=tuple(unknown),
        conflict_fields=tuple(conflicts),
        source_refs=tuple(sorted(source_refs)),
    )


def _build_profile_stats(
    *,
    profile: CategoryProfile,
    rows: tuple[PilotCoverageRow, ...],
) -> ProfileCoverageStats:
    profile_rows = tuple(
        row for row in rows if row.category_profile is profile
    )
    return ProfileCoverageStats(
        category_profile=profile,
        pilot_count=len(profile_rows),
        approved=sum(
            len(row.approved_known_fields) for row in profile_rows
        ),
        unknown=sum(len(row.unknown_fields) for row in profile_rows),
        conflict=sum(len(row.conflict_fields) for row in profile_rows),
    )


def _render_markdown(
    report: PilotCoverageReport,
    *,
    facts_file: str,
    facts_sha256: str,
    fact_count: int,
) -> str:
    approved = sum(stats.approved for stats in report.profile_stats)
    unknown = sum(stats.unknown for stats in report.profile_stats)
    conflict = sum(stats.conflict for stats in report.profile_stats)
    lines = [
        "# Category Pilot Coverage",
        "",
        "## Release Boundary",
        "",
        f"- Facts generation: `{facts_file}`",
        f"- Facts SHA-256: `{facts_sha256}`",
        f"- Approved fact rows: `fact_count={fact_count}`",
        (
            f"- Coverage totals: `approved={approved}`, "
            f"`unknown={unknown}`, `conflict={conflict}`"
        ),
        (
            "- `unknown` means no independently approved fact is "
            "available; it is not a pseudo-value."
        ),
        (
            "- Historical review candidate counts `336/111` are "
            "unrelated to this pilot coverage report and are not "
            "category facts."
        ),
        (
            "- Approved fields passed both independent verifiers; "
            "missing fields remain `unknown`."
        ),
        "",
        "## Profile Summary",
        "",
        "| profile | pilots | approved | unknown | conflict |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    lines.extend(
        (
            f"| `{stats.category_profile.value}` | "
            f"{stats.pilot_count} | {stats.approved} | "
            f"{stats.unknown} | {stats.conflict} |"
        )
        for stats in report.profile_stats
    )
    lines.extend(
        [
            "",
            "## Pilot Matrix",
            "",
            (
                "| profile | product_id | applicable_fields | "
                "approved_known_fields | unknown_fields | "
                "conflict_fields | source_refs |"
            ),
            "| --- | ---: | --- | --- | --- | --- | --- |",
        ]
    )
    lines.extend(_render_row(row) for row in report.rows)
    return "\n".join(lines) + "\n"


def _render_row(row: PilotCoverageRow) -> str:
    return (
        f"| `{row.category_profile.value}` | {row.product_id} | "
        f"{_render_values(row.applicable_fields)} | "
        f"{_render_values(row.approved_known_fields)} | "
        f"{_render_values(row.unknown_fields)} | "
        f"{_render_values(row.conflict_fields)} | "
        f"{_render_values(row.source_refs)} |"
    )


def _render_values(values: tuple[str, ...]) -> str:
    if not values:
        return "-"
    return "<br>".join(f"`{value}`" for value in values)


def _write_atomically(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
            temporary = Path(output.name)
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build deterministic twelve-pilot coverage markdown."
    )
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--facts")
    parser.add_argument("--canonical-manifest", required=True)
    parser.add_argument("--canonical-products", required=True)
    parser.add_argument("--report", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    report = build_category_pilot_coverage(
        manifest_path=args.manifest,
        facts_path=args.facts,
        canonical_manifest_path=args.canonical_manifest,
        canonical_products_path=args.canonical_products,
        report_path=args.report,
    )
    print(
        json.dumps(
            {
                "approved": sum(
                    stats.approved for stats in report.profile_stats
                ),
                "conflict": sum(
                    stats.conflict for stats in report.profile_stats
                ),
                "pilot_count": len(report.rows),
                "unknown": sum(
                    stats.unknown for stats in report.profile_stats
                ),
            },
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
