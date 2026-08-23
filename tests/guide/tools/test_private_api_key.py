from __future__ import annotations

import os
from pathlib import Path

import pytest

from tools.guide_gates.private_api_key import (
    KeyPrecheckCode,
    KeyPrecheckError,
    read_private_api_key,
)


_SECRET = "private-key-must-not-leak"


def _write_key_file(
    path: Path,
    payload: bytes,
    *,
    mode: int = 0o600,
) -> Path:
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        mode,
    )
    try:
        os.write(descriptor, payload)
    finally:
        os.close(descriptor)
    os.chmod(path, mode)
    return path


def test_reads_valid_private_key(tmp_path: Path) -> None:
    key_file = _write_key_file(
        tmp_path / "key",
        _SECRET.encode("utf-8"),
    )

    assert read_private_api_key(key_file) == _SECRET


def test_rejects_symlink_key_file_without_leaking_secret(
    tmp_path: Path,
) -> None:
    target = _write_key_file(
        tmp_path / "real",
        _SECRET.encode("utf-8"),
    )
    link = tmp_path / "link"
    link.symlink_to(target)

    with pytest.raises(KeyPrecheckError) as failure:
        read_private_api_key(link)

    assert failure.value.code is KeyPrecheckCode.SYMLINK
    assert _SECRET not in str(failure.value)


def test_rejects_non_regular_key_file(tmp_path: Path) -> None:
    directory = tmp_path / "dir-key"
    directory.mkdir(mode=0o700)

    with pytest.raises(KeyPrecheckError) as failure:
        read_private_api_key(directory)

    assert failure.value.code is KeyPrecheckCode.NOT_REGULAR


def test_rejects_wrong_key_file_mode(tmp_path: Path) -> None:
    key_file = _write_key_file(
        tmp_path / "key",
        _SECRET.encode("utf-8"),
        mode=0o644,
    )

    with pytest.raises(KeyPrecheckError) as failure:
        read_private_api_key(key_file)

    assert failure.value.code is KeyPrecheckCode.MODE


@pytest.mark.parametrize("payload", [b"", b"k" * 1025])
def test_rejects_invalid_key_file_size(
    tmp_path: Path,
    payload: bytes,
) -> None:
    key_file = _write_key_file(tmp_path / "key", payload)

    with pytest.raises(KeyPrecheckError) as failure:
        read_private_api_key(key_file)

    assert failure.value.code is KeyPrecheckCode.SIZE


def test_rejects_key_edge_whitespace(tmp_path: Path) -> None:
    key_file = _write_key_file(
        tmp_path / "key",
        f"{_SECRET}\n".encode("utf-8"),
    )

    with pytest.raises(KeyPrecheckError) as failure:
        read_private_api_key(key_file)

    assert failure.value.code is KeyPrecheckCode.WHITESPACE


def test_rejects_key_control_character(tmp_path: Path) -> None:
    key_file = _write_key_file(tmp_path / "key", b"abc\x01def")

    with pytest.raises(KeyPrecheckError) as failure:
        read_private_api_key(key_file)

    assert failure.value.code is KeyPrecheckCode.CONTROL


def test_rejects_non_utf8_key(tmp_path: Path) -> None:
    key_file = _write_key_file(
        tmp_path / "key",
        b"\xff\xfe\x00abc",
    )

    with pytest.raises(KeyPrecheckError) as failure:
        read_private_api_key(key_file)

    assert failure.value.code in {
        KeyPrecheckCode.ENCODING,
        KeyPrecheckCode.CONTROL,
    }
