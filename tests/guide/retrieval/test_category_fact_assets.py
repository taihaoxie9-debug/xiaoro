from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from app.guide.adapters.catalog.canonical_product_reader import (
    CanonicalProductReader,
)
from app.guide.retrieval.category_fact_contracts import (
    category_field_registry,
)
from app.guide.retrieval.category_profiles import CategoryProfile


ROOT = Path(__file__).resolve().parents[3]
FIXTURE_DIR = ROOT / "tests" / "fixtures" / "guide" / "category_facts"
FACTS_PATH = FIXTURE_DIR / "approved.jsonl"
MANIFEST_PATH = FIXTURE_DIR / "manifest.json"
EXPECTED_FACTS_SHA256 = (
    "6591aca45d3b1463a95a13063e8ebfc40666d6ac4d8acf464a4ed8853c493eb0"
)
EXPECTED_MANIFEST_SHA256 = (
    "f888b148c677ae9b3635aed5ca8e29c92a34c04e409ad4f2c101b178f1de879f"
)
EXPECTED_MANIFEST_FILE_SHA256 = (
    "aff8a11264161a9e5a9e1ff21e07f04ea53eeade7251d4723ad7ced47a22af84"
)
PILOT_BINDINGS = (
    (CategoryProfile.SKINCARE, 38),
    (CategoryProfile.SKINCARE, 91),
    (CategoryProfile.SUNCARE, 53),
    (CategoryProfile.SUNCARE, 57),
    (CategoryProfile.BASE_MAKEUP, 79),
    (CategoryProfile.BASE_MAKEUP, 80),
    (CategoryProfile.COLOR_MAKEUP, 86),
    (CategoryProfile.COLOR_MAKEUP, 114),
    (CategoryProfile.CLEANSER, 69),
    (CategoryProfile.CLEANSER, 103),
    (CategoryProfile.FRAGRANCE, 120),
    (CategoryProfile.FRAGRANCE, 121),
)


def _asset_api():
    try:
        from app.guide.retrieval.category_fact_assets import (
            CategoryFactAssetIntegrityError,
            load_category_fact_assets,
        )
    except ModuleNotFoundError:
        pytest.fail("category fact asset loader is missing")
    return CategoryFactAssetIntegrityError, load_category_fact_assets


def _canonical_json(payload: object) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _manifest_digest(payload: dict[str, object]) -> str:
    unsigned = {
        key: value
        for key, value in payload.items()
        if key != "manifest_sha256"
    }
    return hashlib.sha256(
        _canonical_json(unsigned).encode("utf-8")
    ).hexdigest()


def _canonical_reader() -> CanonicalProductReader:
    canonical = ROOT / "data" / "canonical"
    return CanonicalProductReader.from_files(
        manifest_path=canonical / "core_products_v1_manifest.json",
        products_path=canonical / "core_products_v1.jsonl",
    )


def _load():
    return _load_paths(
        manifest_path=MANIFEST_PATH,
        facts_path=FACTS_PATH,
    )


def _load_paths(
    *,
    manifest_path: Path,
    facts_path: Path,
    expected_manifest_sha256: str = EXPECTED_MANIFEST_SHA256,
    canonical_reader: object | None = None,
):
    _, load_category_fact_assets = _asset_api()
    return load_category_fact_assets(
        manifest_path=manifest_path,
        facts_path=facts_path,
        expected_manifest_sha256=expected_manifest_sha256,
        canonical_reader=canonical_reader or _canonical_reader(),
        field_registry=category_field_registry(),
    )


def _copy_assets(tmp_path: Path) -> tuple[Path, Path]:
    manifest_path = tmp_path / MANIFEST_PATH.name
    facts_path = tmp_path / FACTS_PATH.name
    shutil.copy2(MANIFEST_PATH, manifest_path)
    shutil.copy2(FACTS_PATH, facts_path)
    return manifest_path, facts_path


def _fact_rows(path: Path = FACTS_PATH) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
    ]


def _fact_digest(row: dict[str, object]) -> str:
    unsigned = {
        key: value
        for key, value in row.items()
        if key != "fact_id"
    }
    return hashlib.sha256(
        _canonical_json(unsigned).encode("utf-8")
    ).hexdigest()


def _write_fact_bytes(
    *,
    manifest_path: Path,
    facts_path: Path,
    fact_bytes: bytes,
    fact_count: int,
) -> str:
    facts_path.write_bytes(fact_bytes)
    facts_sha256 = hashlib.sha256(fact_bytes).hexdigest()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["fact_count"] = fact_count
    manifest["facts_sha256"] = facts_sha256
    manifest["asset_version"] = (
        f"approved-category-facts-v1:sha256:{facts_sha256}"
    )
    manifest["manifest_sha256"] = _manifest_digest(manifest)
    manifest_path.write_text(
        _canonical_json(manifest) + "\n",
        encoding="utf-8",
    )
    return str(manifest["manifest_sha256"])


def _rewrite_facts(
    *,
    manifest_path: Path,
    facts_path: Path,
    rows: list[dict[str, object]],
    readdress: bool = True,
    sort_rows: bool = True,
) -> str:
    if readdress:
        for row in rows:
            row["fact_id"] = _fact_digest(row)
    if sort_rows:
        rows.sort(key=lambda row: str(row["fact_id"]))
    fact_bytes = "".join(
        f"{_canonical_json(row)}\n" for row in rows
    ).encode("utf-8")
    return _write_fact_bytes(
        manifest_path=manifest_path,
        facts_path=facts_path,
        fact_bytes=fact_bytes,
        fact_count=len(rows),
    )


def _rewrite_manifest(
    manifest_path: Path,
    **updates: object,
) -> str:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest.update(updates)
    manifest["manifest_sha256"] = _manifest_digest(manifest)
    manifest_path.write_text(
        _canonical_json(manifest) + "\n",
        encoding="utf-8",
    )
    return str(manifest["manifest_sha256"])


class _CanonicalReaderOverride:
    def __init__(
        self,
        *,
        product_id: int,
        resolved_state: str,
        value: object,
    ) -> None:
        self._reader = _canonical_reader()
        self._product_id = product_id
        self._resolved_state = resolved_state
        self._value = value

    def get(self, product_id: int):
        product = self._reader.get(product_id)
        if product_id != self._product_id:
            return product
        fields = dict(product.fields)
        fields["category"] = fields["category"].model_copy(
            update={
                "resolved_state": self._resolved_state,
                "value": self._value,
            }
        )
        return product.model_copy(update={"fields": fields})


def test_loader_preserves_content_addressed_sorted_fixture() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    loaded = _load()

    assert hashlib.sha256(FACTS_PATH.read_bytes()).hexdigest() == (
        EXPECTED_FACTS_SHA256
    )
    assert hashlib.sha256(MANIFEST_PATH.read_bytes()).hexdigest() == (
        EXPECTED_MANIFEST_FILE_SHA256
    )
    assert manifest["manifest_sha256"] == _manifest_digest(manifest)
    assert manifest["manifest_sha256"] == EXPECTED_MANIFEST_SHA256
    assert manifest["facts_sha256"] == EXPECTED_FACTS_SHA256
    assert manifest["asset_version"] == (
        f"approved-category-facts-v1:sha256:{EXPECTED_FACTS_SHA256}"
    )

    fact_ids = [item.fact_id for item in loaded.facts]
    assert fact_ids == sorted(fact_ids)
    assert len(fact_ids) == len(set(fact_ids)) == 2
    assert all(item.source_refs for item in loaded.facts)
    assert all(
        item.reviewed_at.utcoffset() is not None
        for item in loaded.facts
    )
    assert loaded.manifest.fact_count == len(loaded.facts)
    assert tuple(
        (binding.category_profile, binding.product_id)
        for binding in loaded.manifest.pilot_bindings
    ) == PILOT_BINDINGS
    assert loaded.pilot_ids == frozenset(
        product_id for _, product_id in PILOT_BINDINGS
    )
    for profile in CategoryProfile:
        assert loaded.pilot_ids_for(profile) == frozenset(
            product_id
            for bound_profile, product_id in PILOT_BINDINGS
            if bound_profile is profile
        )


def test_loader_resolves_content_addressed_facts_file_from_manifest(
    tmp_path: Path,
) -> None:
    manifest_path, facts_path = _copy_assets(tmp_path)
    content_addressed_path = tmp_path / (
        f"category_facts_v1.{EXPECTED_FACTS_SHA256}.jsonl"
    )
    facts_path.rename(content_addressed_path)
    manifest_sha256 = _rewrite_manifest(
        manifest_path,
        facts_file=content_addressed_path.name,
    )
    _, load_category_fact_assets = _asset_api()

    loaded = load_category_fact_assets(
        manifest_path=manifest_path,
        expected_manifest_sha256=manifest_sha256,
        canonical_reader=_canonical_reader(),
        field_registry=category_field_registry(),
    )

    assert len(loaded.facts) == 2


def test_loader_rejects_symlinked_manifest_facts_file(
    tmp_path: Path,
) -> None:
    CategoryFactAssetIntegrityError, load_category_fact_assets = _asset_api()
    manifest_path, facts_path = _copy_assets(tmp_path)
    content_addressed_path = tmp_path / (
        f"category_facts_v1.{EXPECTED_FACTS_SHA256}.jsonl"
    )
    content_addressed_path.symlink_to(facts_path)
    manifest_sha256 = _rewrite_manifest(
        manifest_path,
        facts_file=content_addressed_path.name,
    )

    with pytest.raises(
        CategoryFactAssetIntegrityError,
        match="symlink",
    ):
        load_category_fact_assets(
            manifest_path=manifest_path,
            expected_manifest_sha256=manifest_sha256,
            canonical_reader=_canonical_reader(),
            field_registry=category_field_registry(),
        )


def test_loader_rejects_fact_file_hash_drift(tmp_path: Path) -> None:
    CategoryFactAssetIntegrityError, _ = _asset_api()
    manifest_path, facts_path = _copy_assets(tmp_path)
    facts_path.write_bytes(facts_path.read_bytes() + b"\n")

    with pytest.raises(
        CategoryFactAssetIntegrityError,
        match="asset SHA-256 mismatch",
    ):
        _load_paths(
            manifest_path=manifest_path,
            facts_path=facts_path,
        )


def test_loader_rejects_manifest_self_hash_drift(tmp_path: Path) -> None:
    CategoryFactAssetIntegrityError, _ = _asset_api()
    manifest_path, facts_path = _copy_assets(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["asset_id"] = "tampered-category-facts"
    manifest_path.write_text(
        _canonical_json(manifest) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        CategoryFactAssetIntegrityError,
        match="manifest SHA-256 mismatch",
    ):
        _load_paths(
            manifest_path=manifest_path,
            facts_path=facts_path,
        )


def test_loader_rejects_coordinated_tampering_against_external_lock(
    tmp_path: Path,
) -> None:
    CategoryFactAssetIntegrityError, _ = _asset_api()
    manifest_path, facts_path = _copy_assets(tmp_path)
    rows = _fact_rows(facts_path)
    rows[0]["value"] = ["伪造修护"]
    _rewrite_facts(
        manifest_path=manifest_path,
        facts_path=facts_path,
        rows=rows,
    )

    with pytest.raises(
        CategoryFactAssetIntegrityError,
        match="manifest lock mismatch",
    ):
        _load_paths(
            manifest_path=manifest_path,
            facts_path=facts_path,
        )


def test_loader_rejects_fact_content_address_drift(
    tmp_path: Path,
) -> None:
    CategoryFactAssetIntegrityError, _ = _asset_api()
    manifest_path, facts_path = _copy_assets(tmp_path)
    rows = _fact_rows(facts_path)
    rows[0]["value"] = ["伪造修护"]
    manifest_sha256 = _rewrite_facts(
        manifest_path=manifest_path,
        facts_path=facts_path,
        rows=rows,
        readdress=False,
    )

    with pytest.raises(
        CategoryFactAssetIntegrityError,
        match="content address mismatch",
    ):
        _load_paths(
            manifest_path=manifest_path,
            facts_path=facts_path,
            expected_manifest_sha256=manifest_sha256,
        )


def test_loader_rejects_unknown_product(tmp_path: Path) -> None:
    CategoryFactAssetIntegrityError, _ = _asset_api()
    manifest_path, facts_path = _copy_assets(tmp_path)
    rows = _fact_rows(facts_path)
    rows[0]["product_id"] = 999
    manifest_sha256 = _rewrite_facts(
        manifest_path=manifest_path,
        facts_path=facts_path,
        rows=rows,
    )

    with pytest.raises(
        CategoryFactAssetIntegrityError,
        match="unknown category fact product_id 999",
    ):
        _load_paths(
            manifest_path=manifest_path,
            facts_path=facts_path,
            expected_manifest_sha256=manifest_sha256,
        )


@pytest.mark.parametrize(
    ("resolved_state", "value", "message"),
    [
        ("unknown", None, "requires known category"),
        ("conflict", "精华", "requires known category"),
        ("known", "未注册品类", "has unmapped category"),
    ],
)
def test_loader_requires_known_mapped_canonical_category(
    tmp_path: Path,
    resolved_state: str,
    value: object,
    message: str,
) -> None:
    CategoryFactAssetIntegrityError, _ = _asset_api()
    manifest_path, facts_path = _copy_assets(tmp_path)

    with pytest.raises(CategoryFactAssetIntegrityError, match=message):
        _load_paths(
            manifest_path=manifest_path,
            facts_path=facts_path,
            canonical_reader=_CanonicalReaderOverride(
                product_id=38,
                resolved_state=resolved_state,
                value=value,
            ),
        )


def test_loader_rejects_category_profile_mismatch(
    tmp_path: Path,
) -> None:
    CategoryFactAssetIntegrityError, _ = _asset_api()
    manifest_path, facts_path = _copy_assets(tmp_path)
    rows = _fact_rows(facts_path)
    rows[0]["category_profile"] = "fragrance"
    manifest_sha256 = _rewrite_facts(
        manifest_path=manifest_path,
        facts_path=facts_path,
        rows=rows,
    )

    with pytest.raises(
        CategoryFactAssetIntegrityError,
        match="product/profile mismatch",
    ):
        _load_paths(
            manifest_path=manifest_path,
            facts_path=facts_path,
            expected_manifest_sha256=manifest_sha256,
        )


@pytest.mark.parametrize(
    ("field_key", "source_class", "message"),
    [
        (
            "spf_pa",
            "official_packaging",
            "field is not applicable",
        ),
        (
            "unregistered_field",
            "structured_official",
            "field is not applicable",
        ),
        (
            "efficacy",
            "approved_consumer_review",
            "source is not authorized",
        ),
    ],
)
def test_loader_enforces_registry_applicability_and_source_authority(
    tmp_path: Path,
    field_key: str,
    source_class: str,
    message: str,
) -> None:
    CategoryFactAssetIntegrityError, _ = _asset_api()
    manifest_path, facts_path = _copy_assets(tmp_path)
    rows = _fact_rows(facts_path)
    rows[0]["field_key"] = field_key
    rows[0]["source_class"] = source_class
    manifest_sha256 = _rewrite_facts(
        manifest_path=manifest_path,
        facts_path=facts_path,
        rows=rows,
    )

    with pytest.raises(CategoryFactAssetIntegrityError, match=message):
        _load_paths(
            manifest_path=manifest_path,
            facts_path=facts_path,
            expected_manifest_sha256=manifest_sha256,
        )


@pytest.mark.parametrize(
    ("field_key", "source_class"),
    [
        ("brand", "canonical_core"),
        ("efficacy", "unknown"),
    ],
)
def test_loader_rejects_core_overrides_and_unknown_sources(
    tmp_path: Path,
    field_key: str,
    source_class: str,
) -> None:
    CategoryFactAssetIntegrityError, _ = _asset_api()
    manifest_path, facts_path = _copy_assets(tmp_path)
    rows = _fact_rows(facts_path)
    rows[0]["field_key"] = field_key
    rows[0]["source_class"] = source_class
    rows[0]["value"] = "伪造品牌" if field_key == "brand" else ["修护"]
    manifest_sha256 = _rewrite_facts(
        manifest_path=manifest_path,
        facts_path=facts_path,
        rows=rows,
    )

    with pytest.raises(
        CategoryFactAssetIntegrityError,
        match="forbidden in approved category fact sidecar",
    ):
        _load_paths(
            manifest_path=manifest_path,
            facts_path=facts_path,
            expected_manifest_sha256=manifest_sha256,
        )


@pytest.mark.parametrize(
    ("field_key", "value"),
    [
        ("efficacy", "修护"),
        ("double_cleanse", "false"),
        ("price", "100"),
    ],
)
def test_loader_rejects_values_outside_registry_value_type(
    tmp_path: Path,
    field_key: str,
    value: object,
) -> None:
    CategoryFactAssetIntegrityError, _ = _asset_api()
    manifest_path, facts_path = _copy_assets(tmp_path)
    rows = _fact_rows(facts_path)
    row = rows[0]
    row["field_key"] = field_key
    row["value"] = value
    if field_key == "double_cleanse":
        row["product_id"] = 69
        row["category_profile"] = "cleanser"
    elif field_key == "price":
        row["source_class"] = "canonical_core"
    manifest_sha256 = _rewrite_facts(
        manifest_path=manifest_path,
        facts_path=facts_path,
        rows=rows,
    )

    expected_message = (
        "forbidden in approved category fact sidecar"
        if field_key == "price"
        else "value type mismatch"
    )
    with pytest.raises(
        CategoryFactAssetIntegrityError,
        match=expected_message,
    ):
        _load_paths(
            manifest_path=manifest_path,
            facts_path=facts_path,
            expected_manifest_sha256=manifest_sha256,
        )


@pytest.mark.parametrize("source_refs", [["urn:z", "urn:a"], ["urn:a", "urn:a"]])
def test_loader_rejects_noncanonical_source_refs(
    tmp_path: Path,
    source_refs: list[str],
) -> None:
    CategoryFactAssetIntegrityError, _ = _asset_api()
    manifest_path, facts_path = _copy_assets(tmp_path)
    rows = _fact_rows(facts_path)
    rows[0]["source_refs"] = source_refs
    manifest_sha256 = _rewrite_facts(
        manifest_path=manifest_path,
        facts_path=facts_path,
        rows=rows,
    )

    with pytest.raises(
        CategoryFactAssetIntegrityError,
        match="source_refs must be sorted and unique",
    ):
        _load_paths(
            manifest_path=manifest_path,
            facts_path=facts_path,
            expected_manifest_sha256=manifest_sha256,
        )


def test_loader_rejects_conflicting_stable_source_identity(
    tmp_path: Path,
) -> None:
    CategoryFactAssetIntegrityError, _ = _asset_api()
    manifest_path, facts_path = _copy_assets(tmp_path)
    rows = _fact_rows(facts_path)
    conflicting = dict(rows[0])
    conflicting["value"] = ["冲突功效"]
    conflicting["reviewer"] = "reviewer_fixture_003"
    rows.append(conflicting)
    manifest_sha256 = _rewrite_facts(
        manifest_path=manifest_path,
        facts_path=facts_path,
        rows=rows,
    )

    with pytest.raises(
        CategoryFactAssetIntegrityError,
        match="conflicting stable source identity",
    ):
        _load_paths(
            manifest_path=manifest_path,
            facts_path=facts_path,
            expected_manifest_sha256=manifest_sha256,
        )


def test_loader_rejects_naive_reviewed_at(tmp_path: Path) -> None:
    CategoryFactAssetIntegrityError, _ = _asset_api()
    manifest_path, facts_path = _copy_assets(tmp_path)
    rows = _fact_rows(facts_path)
    rows[0]["reviewed_at"] = "2026-08-10T00:00:00"
    manifest_sha256 = _rewrite_facts(
        manifest_path=manifest_path,
        facts_path=facts_path,
        rows=rows,
    )

    with pytest.raises(
        CategoryFactAssetIntegrityError,
        match="invalid category fact at line",
    ):
        _load_paths(
            manifest_path=manifest_path,
            facts_path=facts_path,
            expected_manifest_sha256=manifest_sha256,
        )


@pytest.mark.parametrize(
    ("field", "unsafe_value", "message"),
    [
        ("value", "<article>raw source</article>", "raw HTML"),
        ("value", "联系电话：13800138000", "PII"),
        ("source_refs", ["/private/tmp/source.html"], "absolute path"),
        ("reviewer", "reviewer@example.com", "PII"),
    ],
)
def test_loader_rejects_raw_html_absolute_paths_and_pii(
    tmp_path: Path,
    field: str,
    unsafe_value: object,
    message: str,
) -> None:
    CategoryFactAssetIntegrityError, _ = _asset_api()
    manifest_path, facts_path = _copy_assets(tmp_path)
    rows = _fact_rows(facts_path)
    rows[0][field] = unsafe_value
    if field == "value":
        rows[0]["field_key"] = "reapplication"
        rows[0]["product_id"] = 53
        rows[0]["category_profile"] = "suncare"
        rows[0]["source_class"] = "official_packaging"
    manifest_sha256 = _rewrite_facts(
        manifest_path=manifest_path,
        facts_path=facts_path,
        rows=rows,
    )

    with pytest.raises(CategoryFactAssetIntegrityError, match=message):
        _load_paths(
            manifest_path=manifest_path,
            facts_path=facts_path,
            expected_manifest_sha256=manifest_sha256,
        )


@pytest.mark.parametrize(
    ("field", "unsafe_value"),
    [
        (
            "source_refs",
            ["urn:fixture:/private/tmp/source.html"],
        ),
        (
            "reviewer",
            r"reviewer fixture C:\Users\reviewer\source.html",
        ),
        (
            "value",
            "official reference file:/private/tmp/source.html",
        ),
        (
            "source_refs",
            ["urn:fixture:file://localhost/private/tmp/source.html"],
        ),
        (
            "source_refs",
            [
                "urn:fixture:"
                "file%253A%252F%252Flocalhost%252Fprivate%252Ftmp"
                "%252Fsource.html"
            ],
        ),
    ],
)
def test_loader_rejects_embedded_local_paths_in_any_fact_string(
    tmp_path: Path,
    field: str,
    unsafe_value: object,
) -> None:
    CategoryFactAssetIntegrityError, _ = _asset_api()
    manifest_path, facts_path = _copy_assets(tmp_path)
    rows = _fact_rows(facts_path)
    rows[0][field] = unsafe_value
    if field == "value":
        rows[0]["field_key"] = "reapplication"
        rows[0]["product_id"] = 53
        rows[0]["category_profile"] = "suncare"
        rows[0]["source_class"] = "official_packaging"
    manifest_sha256 = _rewrite_facts(
        manifest_path=manifest_path,
        facts_path=facts_path,
        rows=rows,
    )

    with pytest.raises(
        CategoryFactAssetIntegrityError,
        match="absolute path",
    ):
        _load_paths(
            manifest_path=manifest_path,
            facts_path=facts_path,
            expected_manifest_sha256=manifest_sha256,
        )


@pytest.mark.parametrize(
    "source_ref",
    [
        "urn:xiaoro:fixture:product:38:efficacy",
        "http://example.test/official/source.html",
        "https://example.test/private/tmp/source.html",
    ],
)
def test_loader_accepts_ordinary_urn_and_http_source_refs(
    tmp_path: Path,
    source_ref: str,
) -> None:
    manifest_path, facts_path = _copy_assets(tmp_path)
    rows = _fact_rows(facts_path)
    rows[0]["source_refs"] = [source_ref]
    manifest_sha256 = _rewrite_facts(
        manifest_path=manifest_path,
        facts_path=facts_path,
        rows=rows,
    )

    loaded = _load_paths(
        manifest_path=manifest_path,
        facts_path=facts_path,
        expected_manifest_sha256=manifest_sha256,
    )

    assert loaded.facts[0].source_refs == (source_ref,)


def test_loader_rejects_unsorted_facts_instead_of_sorting(
    tmp_path: Path,
) -> None:
    CategoryFactAssetIntegrityError, _ = _asset_api()
    manifest_path, facts_path = _copy_assets(tmp_path)
    rows = list(reversed(_fact_rows(facts_path)))
    manifest_sha256 = _rewrite_facts(
        manifest_path=manifest_path,
        facts_path=facts_path,
        rows=rows,
        sort_rows=False,
    )

    with pytest.raises(
        CategoryFactAssetIntegrityError,
        match="sorted by fact_id",
    ):
        _load_paths(
            manifest_path=manifest_path,
            facts_path=facts_path,
            expected_manifest_sha256=manifest_sha256,
        )


def test_loader_collapses_exact_duplicates_with_unique_manifest_count(
    tmp_path: Path,
) -> None:
    manifest_path, facts_path = _copy_assets(tmp_path)
    rows = _fact_rows(facts_path)
    rows.append(dict(rows[0]))
    _rewrite_facts(
        manifest_path=manifest_path,
        facts_path=facts_path,
        rows=rows,
    )
    manifest_sha256 = _rewrite_manifest(
        manifest_path,
        fact_count=2,
    )

    loaded = _load_paths(
        manifest_path=manifest_path,
        facts_path=facts_path,
        expected_manifest_sha256=manifest_sha256,
    )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    fact_ids = [fact.fact_id for fact in loaded.facts]
    assert len(facts_path.read_text(encoding="utf-8").splitlines()) == 3
    assert manifest["facts_sha256"] == hashlib.sha256(
        facts_path.read_bytes()
    ).hexdigest()
    assert loaded.manifest.fact_count == len(loaded.facts) == 2
    assert fact_ids == sorted(set(fact_ids))


def test_loader_rejects_duplicate_fact_id_with_different_content(
    tmp_path: Path,
) -> None:
    CategoryFactAssetIntegrityError, _ = _asset_api()
    manifest_path, facts_path = _copy_assets(tmp_path)
    rows = _fact_rows(facts_path)
    conflicting = dict(rows[0])
    conflicting["value"] = ["冲突功效"]
    rows.append(conflicting)
    _rewrite_facts(
        manifest_path=manifest_path,
        facts_path=facts_path,
        rows=rows,
        readdress=False,
    )
    manifest_sha256 = _rewrite_manifest(
        manifest_path,
        fact_count=2,
    )

    with pytest.raises(
        CategoryFactAssetIntegrityError,
        match="content address mismatch",
    ):
        _load_paths(
            manifest_path=manifest_path,
            facts_path=facts_path,
            expected_manifest_sha256=manifest_sha256,
        )


@pytest.mark.parametrize(
    "mutation",
    ["missing", "profile_mismatch", "reordered"],
)
def test_loader_requires_exact_complete_pilot_bindings(
    tmp_path: Path,
    mutation: str,
) -> None:
    CategoryFactAssetIntegrityError, _ = _asset_api()
    manifest_path, facts_path = _copy_assets(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    bindings = list(manifest["pilot_bindings"])
    if mutation == "missing":
        bindings.pop()
    elif mutation == "profile_mismatch":
        bindings[0] = {
            **bindings[0],
            "category_profile": "fragrance",
        }
    else:
        bindings[0], bindings[1] = bindings[1], bindings[0]
    manifest_sha256 = _rewrite_manifest(
        manifest_path,
        pilot_bindings=bindings,
    )

    with pytest.raises(
        CategoryFactAssetIntegrityError,
        match="invalid category fact manifest",
    ):
        _load_paths(
            manifest_path=manifest_path,
            facts_path=facts_path,
            expected_manifest_sha256=manifest_sha256,
        )


def test_loader_accepts_zero_byte_facts_when_count_is_zero(
    tmp_path: Path,
) -> None:
    manifest_path, facts_path = _copy_assets(tmp_path)
    manifest_sha256 = _write_fact_bytes(
        manifest_path=manifest_path,
        facts_path=facts_path,
        fact_bytes=b"",
        fact_count=0,
    )

    loaded = _load_paths(
        manifest_path=manifest_path,
        facts_path=facts_path,
        expected_manifest_sha256=manifest_sha256,
    )

    assert loaded.manifest.fact_count == 0
    assert loaded.facts == ()
    assert loaded.pilot_ids == frozenset(
        product_id for _, product_id in PILOT_BINDINGS
    )


def test_loader_rejects_blank_line_for_zero_count_asset(
    tmp_path: Path,
) -> None:
    CategoryFactAssetIntegrityError, _ = _asset_api()
    manifest_path, facts_path = _copy_assets(tmp_path)
    manifest_sha256 = _write_fact_bytes(
        manifest_path=manifest_path,
        facts_path=facts_path,
        fact_bytes=b"\n",
        fact_count=0,
    )

    with pytest.raises(
        CategoryFactAssetIntegrityError,
        match="blank category fact line 1",
    ):
        _load_paths(
            manifest_path=manifest_path,
            facts_path=facts_path,
            expected_manifest_sha256=manifest_sha256,
        )


def test_manifest_lock_uses_logical_self_hash_not_raw_file_hash(
    tmp_path: Path,
) -> None:
    manifest_path, facts_path = _copy_assets(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    assert hashlib.sha256(manifest_path.read_bytes()).hexdigest() != (
        EXPECTED_MANIFEST_FILE_SHA256
    )
    loaded = _load_paths(
        manifest_path=manifest_path,
        facts_path=facts_path,
    )
    assert loaded.manifest.manifest_sha256 == EXPECTED_MANIFEST_SHA256


@pytest.mark.parametrize(
    "asset_id",
    [
        "/private/tmp/category-facts",
        "<article>category-facts</article>",
        "reviewer@example.com",
    ],
)
def test_loader_rejects_unsafe_manifest_asset_id(
    tmp_path: Path,
    asset_id: str,
) -> None:
    CategoryFactAssetIntegrityError, _ = _asset_api()
    manifest_path, facts_path = _copy_assets(tmp_path)
    manifest_sha256 = _rewrite_manifest(
        manifest_path,
        asset_id=asset_id,
    )

    with pytest.raises(
        CategoryFactAssetIntegrityError,
        match="invalid category fact manifest",
    ):
        _load_paths(
            manifest_path=manifest_path,
            facts_path=facts_path,
            expected_manifest_sha256=manifest_sha256,
        )


@pytest.mark.parametrize(
    ("updates", "message"),
    [
        ({"fact_count": 3}, "category fact count mismatch"),
        (
            {"asset_version": "approved-category-facts-v1:sha256:" + "c" * 64},
            "asset version is not content-addressed",
        ),
        ({"facts_file": "other.jsonl"}, "facts_file mismatch"),
        ({"raw_html": "<html>source</html>"}, "invalid category fact manifest"),
    ],
)
def test_loader_rejects_manifest_contract_drift(
    tmp_path: Path,
    updates: dict[str, object],
    message: str,
) -> None:
    CategoryFactAssetIntegrityError, _ = _asset_api()
    manifest_path, facts_path = _copy_assets(tmp_path)
    manifest_sha256 = _rewrite_manifest(manifest_path, **updates)

    with pytest.raises(CategoryFactAssetIntegrityError, match=message):
        _load_paths(
            manifest_path=manifest_path,
            facts_path=facts_path,
            expected_manifest_sha256=manifest_sha256,
        )
