from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from urllib import error as urllib_error
from urllib import request as urllib_request

from ..config import ConfigManager

DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEFAULT_MODEL = "qwen-plus"
DEFAULT_EMBEDDING_MODEL = "text-embedding-v4"
DEFAULT_TEMPERATURE = 0.2
DEFAULT_TIMEOUT_SECONDS = 120.0


def parse_json_object(text: str) -> dict[str, Any]:
    """Parse a JSON object from an LLM response, tolerating code fences."""
    cleaned = str(text or "").strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start == -1 or end <= start:
            raise ValueError(f"Expected a JSON object but got: {text[:300]}") from None
        payload = json.loads(cleaned[start : end + 1])
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object but got: {text[:300]}")
    return payload


class QwenClient:
    """Minimal DashScope compatible-mode client used by memory LLM calls.

    Settings are resolved from ``runners.qwen`` in runners.yaml (added by the
    Qwen runner branch) and fall back to the ``QWEN_API_KEY`` /
    ``QWEN_BASE_URL`` environment variables. Tests inject a fake client, so
    this class is only exercised against the real API when explicitly wired.
    """

    def __init__(
        self,
        home: Path,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        embedding_model: str | None = None,
        temperature: float | None = None,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        resolved = self._resolve_settings(
            home,
            api_key=api_key,
            base_url=base_url,
            model=model,
            embedding_model=embedding_model,
            temperature=temperature,
        )
        (
            self.api_key,
            self.base_url,
            self.model,
            self.embedding_model,
            self.temperature,
        ) = resolved
        self.base_url = self.base_url.rstrip("/")
        self.timeout_seconds = float(timeout_seconds or DEFAULT_TIMEOUT_SECONDS)

    def chat(self, system: str, user: str, *, json_mode: bool = True) -> str:
        """Run one chat completion and return the assistant message content."""
        if not self.api_key:
            raise ValueError(
                "QWEN_API_KEY is not set. Add it to `runners.qwen.env` in "
                "runners.yaml or set the QWEN_API_KEY environment variable."
            )
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": user})
        payload: dict[str, Any] = {"model": self.model, "messages": messages}
        if self.temperature is not None:
            payload["temperature"] = self.temperature
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        data = self._post("/chat/completions", payload)
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(f"Unexpected Qwen chat response: {str(data)[:500]}") from exc
        return str(content or "").strip()

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed a list of texts and return their vectors in input order."""
        if not self.api_key:
            raise ValueError(
                "QWEN_API_KEY is not set. Add it to `runners.qwen.env` in "
                "runners.yaml or set the QWEN_API_KEY environment variable."
            )
        normalized_texts = [str(text or "") for text in texts]
        payload: dict[str, Any] = {
            "model": self.embedding_model,
            "input": normalized_texts,
        }
        data = self._post("/embeddings", payload)
        items = data.get("data") or []
        if not isinstance(items, list):
            raise RuntimeError(f"Unexpected Qwen embedding response: {str(data)[:500]}")
        items = sorted(items, key=lambda item: int(item.get("index", 0)))
        vectors: list[list[float]] = []
        for item in items:
            vector = item.get("embedding")
            if not isinstance(vector, list):
                raise RuntimeError(f"Unexpected Qwen embedding response: {str(data)[:500]}")
            vectors.append([float(value) for value in vector])
        if len(vectors) != len(normalized_texts):
            raise RuntimeError(
                f"Qwen embedding count mismatch: expected {len(normalized_texts)}, got {len(vectors)}."
            )
        return vectors

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        request = urllib_request.Request(
            f"{self.base_url}/{path.lstrip('/')}",
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib_request.urlopen(request, timeout=self.timeout_seconds) as response:
                raw = response.read().decode("utf-8")
        except urllib_error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise RuntimeError(f"Qwen API error {exc.code}: {detail}") from exc
        except urllib_error.URLError as exc:
            raise RuntimeError(f"Qwen API request failed: {exc.reason}") from exc
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Qwen API returned invalid JSON: {raw[:500]}") from exc

    @classmethod
    def _resolve_settings(
        cls,
        home: Path,
        *,
        api_key: str | None,
        base_url: str | None,
        model: str | None,
        embedding_model: str | None,
        temperature: float | None,
    ) -> tuple[str, str, str, str, float | None]:
        qwen_cfg = cls._load_qwen_config(home)
        env = qwen_cfg.get("env") if isinstance(qwen_cfg.get("env"), dict) else {}
        resolved_key = str(
            api_key
            or env.get("QWEN_API_KEY")
            or os.environ.get("QWEN_API_KEY", "")
        ).strip()
        resolved_base = (
            str(
                base_url
                or qwen_cfg.get("base_url")
                or os.environ.get("QWEN_BASE_URL")
                or DEFAULT_BASE_URL
            ).strip()
            or DEFAULT_BASE_URL
        )
        resolved_model = (
            str(
                model
                or qwen_cfg.get("model")
                or os.environ.get("QWEN_MODEL")
                or DEFAULT_MODEL
            ).strip()
            or DEFAULT_MODEL
        )
        if resolved_model.lower() in {"inherit", "default", "qwen-default"}:
            resolved_model = DEFAULT_MODEL
        resolved_embedding_model = (
            str(
                embedding_model
                or qwen_cfg.get("embedding_model")
                or os.environ.get("QWEN_EMBEDDING_MODEL")
                or DEFAULT_EMBEDDING_MODEL
            ).strip()
            or DEFAULT_EMBEDDING_MODEL
        )
        resolved_temperature = temperature
        if resolved_temperature is None:
            raw_temperature = qwen_cfg.get("temperature")
            try:
                resolved_temperature = (
                    float(raw_temperature) if raw_temperature is not None else DEFAULT_TEMPERATURE
                )
            except (TypeError, ValueError):
                resolved_temperature = DEFAULT_TEMPERATURE
        return (
            resolved_key,
            resolved_base,
            resolved_model,
            resolved_embedding_model,
            resolved_temperature,
        )

    @staticmethod
    def _load_qwen_config(home: Path) -> dict[str, Any]:
        try:
            runners = ConfigManager(home).load_runners_config()
        except Exception:
            runners = {}
        qwen_cfg = (runners or {}).get("qwen") or {}
        return qwen_cfg if isinstance(qwen_cfg, dict) else {}
