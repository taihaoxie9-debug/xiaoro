from __future__ import annotations

from decimal import Decimal
import json
import os
from pathlib import Path

import pytest

from app.guide.adapters.llm.deepseek_intent import DEEPSEEK_V4_PRO_MODEL
from app.guide.adapters.llm.deepseek_two_stage_intent import (
    DEEPSEEK_V4_FLASH_MODEL,
)
from app.guide.adapters.llm.intent_detail_prompt import (
    DETAIL_PROMPT_VERSION,
)
from app.guide.adapters.llm.intent_prompt import INTENT_PROMPT_VERSION
from app.guide.adapters.llm.intent_route_prompt import (
    ROUTE_PROMPT_VERSION,
)
from app.guide_runtime.llm_config import GuideLlmConfig
from tools.guide_gates import run_official_deepseek_smoke as entry
from tools.guide_gates.guide_pipeline_evaluator import (
    ModelVerticalEvaluator,
)
from tools.guide_gates.run_real_deepseek_intent_ab import (
    DeepSeekRunnerConfig,
)


_SECRET = "official-smoke-secret-must-not-leak"
_TWO_STAGE_PROMPT_VERSION = (
    f"{ROUTE_PROMPT_VERSION}+{DETAIL_PROMPT_VERSION}"
)


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


def _guide_config(model: str) -> GuideLlmConfig:
    return GuideLlmConfig(
        api_key="unit-test-key",
        base_url="https://api.deepseek.com",
        model=model,
        timeout_seconds=12.0,
        max_tokens=256,
        daily_budget_cny=Decimal("1.00"),
        daily_call_cap=480,
        format_repair_attempts=1,
        enable_thinking=False,
    )


# --- safe key reading -------------------------------------------------


def test_reads_valid_private_key(tmp_path: Path) -> None:
    key_file = _write_key_file(tmp_path / "key", _SECRET.encode("utf-8"))

    assert entry.read_private_api_key(key_file) == _SECRET


def test_rejects_symlink_key_file(tmp_path: Path) -> None:
    target = _write_key_file(tmp_path / "real", _SECRET.encode("utf-8"))
    link = tmp_path / "link"
    link.symlink_to(target)

    with pytest.raises(entry.KeyPrecheckError) as failure:
        entry.read_private_api_key(link)

    assert failure.value.code is entry.KeyPrecheckCode.SYMLINK
    assert _SECRET not in str(failure.value)


def test_rejects_non_regular_file(tmp_path: Path) -> None:
    directory = tmp_path / "dir-key"
    directory.mkdir(mode=0o700)

    with pytest.raises(entry.KeyPrecheckError) as failure:
        entry.read_private_api_key(directory)

    assert failure.value.code is entry.KeyPrecheckCode.NOT_REGULAR


def test_rejects_wrong_mode(tmp_path: Path) -> None:
    key_file = _write_key_file(
        tmp_path / "key",
        _SECRET.encode("utf-8"),
        mode=0o644,
    )

    with pytest.raises(entry.KeyPrecheckError) as failure:
        entry.read_private_api_key(key_file)

    assert failure.value.code is entry.KeyPrecheckCode.MODE


def test_rejects_empty_file(tmp_path: Path) -> None:
    key_file = _write_key_file(tmp_path / "key", b"")

    with pytest.raises(entry.KeyPrecheckError) as failure:
        entry.read_private_api_key(key_file)

    assert failure.value.code is entry.KeyPrecheckCode.SIZE


def test_rejects_oversized_file(tmp_path: Path) -> None:
    key_file = _write_key_file(tmp_path / "key", b"k" * 1025)

    with pytest.raises(entry.KeyPrecheckError) as failure:
        entry.read_private_api_key(key_file)

    assert failure.value.code is entry.KeyPrecheckCode.SIZE


def test_rejects_trailing_whitespace(tmp_path: Path) -> None:
    key_file = _write_key_file(
        tmp_path / "key",
        f"{_SECRET}\n".encode("utf-8"),
    )

    with pytest.raises(entry.KeyPrecheckError) as failure:
        entry.read_private_api_key(key_file)

    assert failure.value.code is entry.KeyPrecheckCode.WHITESPACE


def test_rejects_control_character(tmp_path: Path) -> None:
    key_file = _write_key_file(
        tmp_path / "key",
        b"abc\x01def",
    )

    with pytest.raises(entry.KeyPrecheckError) as failure:
        entry.read_private_api_key(key_file)

    assert failure.value.code is entry.KeyPrecheckCode.CONTROL


def test_rejects_non_utf8(tmp_path: Path) -> None:
    key_file = _write_key_file(tmp_path / "key", b"\xff\xfe\x00abc")

    with pytest.raises(entry.KeyPrecheckError) as failure:
        entry.read_private_api_key(key_file)

    assert failure.value.code in {
        entry.KeyPrecheckCode.ENCODING,
        entry.KeyPrecheckCode.CONTROL,
    }


# --- factory assembly -------------------------------------------------


def test_two_stage_factory_builds_official_flash_identity() -> None:
    adapter = entry.build_two_stage_adapter(
        _guide_config(DEEPSEEK_V4_FLASH_MODEL)
    )
    try:
        assert adapter.provider == "deepseek_official"
        assert adapter.model == DEEPSEEK_V4_FLASH_MODEL
        assert adapter.base_url == "https://api.deepseek.com"
        assert adapter.prompt_version == _TWO_STAGE_PROMPT_VERSION
    finally:
        adapter.close()


def test_single_stage_factory_builds_pro_control_identity() -> None:
    adapter = entry.build_single_stage_adapter(
        _guide_config(DEEPSEEK_V4_PRO_MODEL)
    )
    try:
        assert adapter.provider == "deepseek_official"
        assert adapter.model == DEEPSEEK_V4_PRO_MODEL
        assert adapter.base_url == "https://api.deepseek.com"
        assert adapter.prompt_version == INTENT_PROMPT_VERSION
    finally:
        adapter.close()


def test_single_stage_factory_rejects_non_pro_model() -> None:
    with pytest.raises(ValueError):
        entry.build_single_stage_adapter(
            _guide_config(DEEPSEEK_V4_FLASH_MODEL)
        )


def test_evaluator_factory_returns_model_vertical_evaluator() -> None:
    assert isinstance(
        entry.evaluator_factory(),
        ModelVerticalEvaluator,
    )


# --- blocked / injection wiring --------------------------------------


def test_main_blocks_on_bad_key_without_invoking_runner(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    bad_key = _write_key_file(
        tmp_path / "key",
        _SECRET.encode("utf-8"),
        mode=0o644,
    )
    output_dir = tmp_path / "must-not-exist"
    calls: list[object] = []

    def spy_runner(argv, **kwargs):
        calls.append((argv, kwargs))
        return 0

    result = entry.main(
        ["--output-dir", str(output_dir)],
        key_path=str(bad_key),
        runner_main=spy_runner,
    )

    assert result != 0
    assert calls == []
    assert not output_dir.exists()
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["code"] == entry.KeyPrecheckCode.MODE.value
    assert payload["status"] == "key_precheck_failed"
    assert _SECRET not in captured.out
    assert _SECRET not in captured.err


def test_main_forwards_injected_dependencies_to_runner(
    tmp_path: Path,
) -> None:
    key_file = _write_key_file(tmp_path / "key", _SECRET.encode("utf-8"))
    output_dir = tmp_path / "evidence"
    captured: dict[str, object] = {}

    def spy_runner(
        argv,
        *,
        config,
        api_key,
        two_stage_adapter_factory,
        single_stage_adapter_factory,
        evaluator_factory,
    ):
        captured["argv"] = list(argv)
        captured["config"] = config
        captured["api_key"] = api_key
        captured["factories"] = (
            two_stage_adapter_factory,
            single_stage_adapter_factory,
            evaluator_factory,
        )
        return 0

    result = entry.main(
        ["--output-dir", str(output_dir)],
        key_path=str(key_file),
        runner_main=spy_runner,
    )

    assert result == 0
    assert captured["argv"] == ["--output-dir", str(output_dir)]
    assert captured["api_key"] == _SECRET
    assert isinstance(captured["config"], DeepSeekRunnerConfig)
    assert captured["config"] == DeepSeekRunnerConfig()
    assert captured["factories"] == (
        entry.build_two_stage_adapter,
        entry.build_single_stage_adapter,
        entry.evaluator_factory,
    )
