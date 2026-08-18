from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat

import pytest

from tools.guide_data import inventory_local_sources
from tools.guide_data.inventory_local_sources import (
    ApprovedSourceRoot,
    SourceInventoryError,
    inventory_sources,
)


def _rows(path: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
    ]


def test_inventory_emits_only_anonymous_relative_metadata(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "sources"
    source_root.mkdir()
    source = source_root / "nested" / "product.html"
    source.parent.mkdir()
    source_bytes = b"<html>private review body</html>"
    source.write_bytes(source_bytes)
    before = source.stat()
    output = tmp_path / "output" / "inventory.jsonl"

    result = inventory_sources(
        roots=[
            ApprovedSourceRoot(
                label="approved-review-fixture",
                path=source_root,
            )
        ],
        output_path=output,
    )

    assert result.overall_status == "complete"
    assert result.file_count == 1
    assert result.missing_root_count == 0
    assert result.output_sha256 == hashlib.sha256(
        output.read_bytes()
    ).hexdigest()
    assert _rows(output) == [
        {
            "content_type": "html",
            "relative_name": "nested/product.html",
            "sha256": hashlib.sha256(source_bytes).hexdigest(),
            "size_bytes": len(source_bytes),
            "source_root_id": hashlib.sha256(
                b"guide-source-root-v1\0approved-review-fixture"
            ).hexdigest(),
        }
    ]
    serialized = output.read_text(encoding="utf-8")
    assert str(tmp_path) not in serialized
    assert "private review body" not in serialized
    assert set(_rows(output)[0]) == {
        "content_type",
        "relative_name",
        "sha256",
        "size_bytes",
        "source_root_id",
    }
    after = source.stat()
    assert source.read_bytes() == source_bytes
    assert after.st_mtime_ns == before.st_mtime_ns
    assert stat.S_IMODE(output.stat().st_mode) == 0o600


def test_root_identity_is_derived_from_label_not_path(
    tmp_path: Path,
) -> None:
    root_ids = []
    for index in (1, 2):
        source_root = tmp_path / f"physical-{index}"
        source_root.mkdir()
        (source_root / "same.json").write_text("{}", encoding="utf-8")
        output = tmp_path / f"inventory-{index}.jsonl"
        inventory_sources(
            roots=[
                ApprovedSourceRoot(
                    label="same-approved-label",
                    path=source_root,
                )
            ],
            output_path=output,
        )
        root_ids.append(_rows(output)[0]["source_root_id"])

    assert root_ids[0] == root_ids[1]


def test_inventory_supports_macos_style_symlinked_root_parent(
    tmp_path: Path,
) -> None:
    physical_parent = tmp_path / "physical"
    source_root = physical_parent / "sources"
    source_root.mkdir(parents=True)
    source_bytes = b"approved"
    (source_root / "source.json").write_bytes(source_bytes)
    alias = tmp_path / "stable-parent-alias"
    alias.symlink_to(physical_parent, target_is_directory=True)
    output = tmp_path / "inventory.jsonl"

    result = inventory_sources(
        roots=[alias / "sources"],
        output_path=output,
    )

    assert result.file_count == 1
    assert _rows(output)[0]["sha256"] == hashlib.sha256(
        source_bytes
    ).hexdigest()


def test_missing_approved_root_marks_overall_inventory_incomplete(
    tmp_path: Path,
) -> None:
    existing = tmp_path / "existing"
    existing.mkdir()
    (existing / "source.json").write_text("{}", encoding="utf-8")
    output = tmp_path / "inventory.jsonl"

    result = inventory_sources(
        roots=[
            ApprovedSourceRoot(label="present", path=existing),
            ApprovedSourceRoot(
                label="missing",
                path=tmp_path / "not-present",
            ),
        ],
        output_path=output,
    )

    assert result.overall_status == "incomplete"
    assert result.root_count == 2
    assert result.missing_root_count == 1
    assert result.file_count == 1


def test_inventory_rejects_output_inside_source_tree(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "sources"
    source_root.mkdir()

    with pytest.raises(
        SourceInventoryError,
        match="output must be outside source roots",
    ):
        inventory_sources(
            roots=[source_root],
            output_path=source_root / "inventory.jsonl",
        )


def test_output_parent_symlink_replacement_race_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_root = tmp_path / "sources"
    source_root.mkdir()
    (source_root / "source.json").write_text("{}", encoding="utf-8")
    output_parent = tmp_path / "output"
    output_parent.mkdir()
    output = output_parent / "inventory.jsonl"
    detached_parent = tmp_path / "detached-output"
    original_write = inventory_local_sources.atomic_write_private
    raced = False

    def replace_parent_before_write(
        output: str | Path,
        content: bytes,
        *,
        forbidden_directory_identities: tuple[tuple[int, int], ...] = (),
    ) -> None:
        nonlocal raced
        output_parent.rename(detached_parent)
        output_parent.symlink_to(source_root, target_is_directory=True)
        raced = True
        original_write(
            output,
            content,
            forbidden_directory_identities=(
                forbidden_directory_identities
            ),
        )

    monkeypatch.setattr(
        inventory_local_sources,
        "atomic_write_private",
        replace_parent_before_write,
    )

    caught: SourceInventoryError | None = None
    try:
        inventory_sources(roots=[source_root], output_path=output)
    except SourceInventoryError as exc:
        caught = exc

    assert raced is True
    assert not (source_root / output.name).exists(), (
        "output parent replacement wrote inventory into source tree"
    )
    assert caught is not None, "output parent replacement was accepted"


def test_post_rename_parent_inode_drift_rolls_back_published_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_parent = tmp_path / "output"
    output_parent.mkdir()
    output = output_parent / "inventory.jsonl"
    detached_parent = tmp_path / "detached-output"
    original_rename = os.rename
    raced = False

    def replace_parent_after_publication(
        source: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        destination: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        *,
        src_dir_fd: int | None = None,
        dst_dir_fd: int | None = None,
    ) -> None:
        nonlocal raced
        original_rename(
            source,
            destination,
            src_dir_fd=src_dir_fd,
            dst_dir_fd=dst_dir_fd,
        )
        if dst_dir_fd is not None and destination == output.name:
            original_rename(output_parent, detached_parent)
            output_parent.mkdir()
            raced = True

    monkeypatch.setattr(
        inventory_local_sources.os,
        "rename",
        replace_parent_after_publication,
    )

    with pytest.raises(
        SourceInventoryError,
        match="output parent changed during publication",
    ):
        inventory_local_sources.atomic_write_private(output, b"inventory\n")

    assert raced is True
    assert not output.exists()
    assert not (detached_parent / output.name).exists()
    assert list(output_parent.iterdir()) == []
    assert list(detached_parent.iterdir()) == []


def test_post_rename_parent_moved_into_source_tree_rolls_back_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_root = tmp_path / "sources"
    source_root.mkdir()
    source_metadata = source_root.stat()
    output_parent = tmp_path / "output"
    output_parent.mkdir()
    output = output_parent / "inventory.jsonl"
    moved_parent = source_root / "moved-output"
    original_rename = os.rename
    raced = False

    def move_parent_after_publication(
        source: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        destination: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        *,
        src_dir_fd: int | None = None,
        dst_dir_fd: int | None = None,
    ) -> None:
        nonlocal raced
        original_rename(
            source,
            destination,
            src_dir_fd=src_dir_fd,
            dst_dir_fd=dst_dir_fd,
        )
        if dst_dir_fd is not None and destination == output.name:
            original_rename(output_parent, moved_parent)
            raced = True

    monkeypatch.setattr(
        inventory_local_sources.os,
        "rename",
        move_parent_after_publication,
    )

    with pytest.raises(
        SourceInventoryError,
        match="output parent changed during publication|"
        "output must be outside source roots",
    ):
        inventory_local_sources.atomic_write_private(
            output,
            b"inventory\n",
            forbidden_directory_identities=(
                inventory_local_sources._inode_identity(source_metadata),
            ),
        )

    assert raced is True
    assert not output.exists()
    assert not (moved_parent / output.name).exists()
    assert list(moved_parent.iterdir()) == []


@pytest.mark.parametrize("entry_kind", ["symlink", "fifo"])
def test_inventory_rejects_symlink_and_non_regular_entries(
    tmp_path: Path,
    entry_kind: str,
) -> None:
    source_root = tmp_path / "sources"
    source_root.mkdir()
    if entry_kind == "symlink":
        target = tmp_path / "target.html"
        target.write_text("not approved", encoding="utf-8")
        (source_root / "source.html").symlink_to(target)
    else:
        os.mkfifo(source_root / "source.html")

    with pytest.raises(
        SourceInventoryError,
        match="source entries must be regular files or directories",
    ):
        inventory_sources(
            roots=[source_root],
            output_path=tmp_path / "inventory.jsonl",
        )


def test_inventory_failure_preserves_existing_output(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "sources"
    source_root.mkdir()
    target = tmp_path / "target.json"
    target.write_text("{}", encoding="utf-8")
    (source_root / "bad.json").symlink_to(target)
    output = tmp_path / "inventory.jsonl"
    original = b"existing inventory\n"
    output.write_bytes(original)

    with pytest.raises(SourceInventoryError):
        inventory_sources(roots=[source_root], output_path=output)

    assert output.read_bytes() == original


def test_directory_symlink_replacement_race_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_root = tmp_path / "sources"
    nested = source_root / "nested"
    nested.mkdir(parents=True)
    safe_bytes = b"approved source"
    (nested / "source.html").write_bytes(safe_bytes)

    outside = tmp_path / "outside"
    outside.mkdir()
    outside_bytes = b"outside approved root"
    (outside / "source.html").write_bytes(outside_bytes)

    output = tmp_path / "inventory.jsonl"
    original_output = b"existing inventory\n"
    output.write_bytes(original_output)
    original_inspection = inventory_local_sources._require_regular_file
    replacement = source_root / "detached-original"
    raced = False

    def replace_ancestor_before_file_inspection(
        *args: object,
        **kwargs: object,
    ) -> os.stat_result:
        nonlocal raced
        if not raced:
            raced = True
            nested.rename(replacement)
            nested.symlink_to(outside, target_is_directory=True)
        return original_inspection(*args, **kwargs)

    monkeypatch.setattr(
        inventory_local_sources,
        "_require_regular_file",
        replace_ancestor_before_file_inspection,
    )

    with pytest.raises(
        SourceInventoryError,
        match="source entr(?:y|ies).*changed|regular files or directories",
    ):
        inventory_sources(roots=[source_root], output_path=output)

    assert raced is True
    assert output.read_bytes() == original_output
    outside_digest = hashlib.sha256(outside_bytes).hexdigest().encode()
    assert outside_digest not in output.read_bytes()


def test_explicit_incomplete_mode_rejects_unsafe_entry_and_continues(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "sources"
    source_root.mkdir()
    (source_root / "safe.json").write_text("{}", encoding="utf-8")
    target = tmp_path / "outside.json"
    target.write_text('{"private": true}', encoding="utf-8")
    (source_root / "unsafe.json").symlink_to(target)
    output = tmp_path / "inventory.jsonl"

    result = inventory_sources(
        roots=[source_root],
        output_path=output,
        continue_on_rejected_entries=True,
    )

    assert result.overall_status == "incomplete"
    assert result.rejected_entry_count == 1
    assert result.file_count == 1
    assert _rows(output)[0]["relative_name"] == "safe.json"
    assert "private" not in output.read_text(encoding="utf-8")


def test_inventory_skips_unsupported_regular_files(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "sources"
    source_root.mkdir()
    (source_root / "notes.txt").write_text("private", encoding="utf-8")
    (source_root / "image.PNG").write_bytes(b"png")
    output = tmp_path / "inventory.jsonl"

    result = inventory_sources(
        roots=[source_root],
        output_path=output,
    )

    assert result.file_count == 1
    assert result.skipped_file_count == 1
    assert _rows(output)[0]["content_type"] == "png"
