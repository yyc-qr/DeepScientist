from __future__ import annotations

from pathlib import Path

import pytest

from deepscientist.memory.qwen import (
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    QwenClient,
    parse_json_object,
)


def test_parse_json_object_tolerates_code_fences() -> None:
    payload = parse_json_object('```json\n{"category": "timeout", "reason": "OOM"}\n```')
    assert payload == {"category": "timeout", "reason": "OOM"}


def test_parse_json_object_extracts_embedded_object() -> None:
    payload = parse_json_object('Here is the result: {"category": "marginal"} done')
    assert payload == {"category": "marginal"}


def test_parse_json_object_rejects_non_object() -> None:
    with pytest.raises(ValueError, match="Expected a JSON object"):
        parse_json_object("no json here")


def test_qwen_client_resolves_settings_from_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("QWEN_API_KEY", "env-key")
    monkeypatch.setenv("QWEN_BASE_URL", "https://example.invalid/v1")
    client = QwenClient(tmp_path)
    assert client.api_key == "env-key"
    assert client.base_url == "https://example.invalid/v1"
    assert client.model == DEFAULT_MODEL


def test_qwen_client_falls_back_to_defaults(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("QWEN_API_KEY", raising=False)
    monkeypatch.delenv("QWEN_BASE_URL", raising=False)
    client = QwenClient(tmp_path)
    assert client.api_key == ""
    assert client.base_url == DEFAULT_BASE_URL
    assert client.model == DEFAULT_MODEL


def test_qwen_client_chat_requires_api_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("QWEN_API_KEY", raising=False)
    client = QwenClient(tmp_path)
    with pytest.raises(ValueError, match="QWEN_API_KEY is not set"):
        client.chat(system="s", user="u")
