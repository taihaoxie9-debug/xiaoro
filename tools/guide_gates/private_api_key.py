from __future__ import annotations

from enum import Enum
import errno
import os
from pathlib import Path
import stat


DEFAULT_KEY_PATH = "/private/tmp/xiaoro-deepseek-api-key"
_MAX_KEY_BYTES = 1024
_EXPECTED_KEY_MODE = 0o600


class KeyPrecheckCode(str, Enum):
    UNAVAILABLE = "key_unavailable"
    SYMLINK = "key_is_symlink"
    NOT_REGULAR = "key_not_regular_file"
    MODE = "key_mode_not_0600"
    SIZE = "key_size_out_of_range"
    ENCODING = "key_not_utf8"
    WHITESPACE = "key_has_edge_whitespace"
    CONTROL = "key_has_control_character"


class KeyPrecheckError(Exception):
    def __init__(self, code: KeyPrecheckCode) -> None:
        self.code = code
        super().__init__(code.value)


def read_private_api_key(path: str | Path) -> str:
    key_path = Path(path)
    try:
        link_status = os.lstat(key_path)
    except OSError as exc:
        raise KeyPrecheckError(KeyPrecheckCode.UNAVAILABLE) from exc
    _validate_status(link_status)

    try:
        descriptor = os.open(
            key_path,
            os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
        )
    except OSError as exc:
        code = (
            KeyPrecheckCode.SYMLINK
            if getattr(exc, "errno", None) == errno.ELOOP
            else KeyPrecheckCode.UNAVAILABLE
        )
        raise KeyPrecheckError(code) from exc

    try:
        _validate_status(os.fstat(descriptor))
        raw = os.read(descriptor, _MAX_KEY_BYTES + 1)
    finally:
        os.close(descriptor)

    if not raw or len(raw) > _MAX_KEY_BYTES:
        raise KeyPrecheckError(KeyPrecheckCode.SIZE)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise KeyPrecheckError(KeyPrecheckCode.ENCODING) from exc
    if text != text.strip():
        raise KeyPrecheckError(KeyPrecheckCode.WHITESPACE)
    if any(
        ord(character) < 32 or ord(character) == 127
        for character in text
    ):
        raise KeyPrecheckError(KeyPrecheckCode.CONTROL)
    return text


def _validate_status(status: os.stat_result) -> None:
    if stat.S_ISLNK(status.st_mode):
        raise KeyPrecheckError(KeyPrecheckCode.SYMLINK)
    if not stat.S_ISREG(status.st_mode):
        raise KeyPrecheckError(KeyPrecheckCode.NOT_REGULAR)
    if stat.S_IMODE(status.st_mode) != _EXPECTED_KEY_MODE:
        raise KeyPrecheckError(KeyPrecheckCode.MODE)
    if not 1 <= status.st_size <= _MAX_KEY_BYTES:
        raise KeyPrecheckError(KeyPrecheckCode.SIZE)


__all__ = [
    "DEFAULT_KEY_PATH",
    "KeyPrecheckCode",
    "KeyPrecheckError",
    "read_private_api_key",
]
