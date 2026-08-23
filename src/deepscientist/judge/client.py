from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

import httpx

from .schemas import PaperJudgeError


@dataclass(frozen=True)
class JudgeClientConfig:
    provider: str = "openai_compatible"
    api_base: str | None = None
    api_key: str | None = None
    api_key_env: str | None = None
    model: str | None = None
    temperature: float = 0.1
    max_output_tokens: int = 6000
    timeout_seconds: float = 120.0
    empty_response_max_attempts: int = 3
    thinking: str = "auto"


def resolve_api_key(config: JudgeClientConfig) -> str | None:
    if config.api_key:
        return config.api_key
    if config.api_key_env:
        value = os.environ.get(config.api_key_env)
        if value:
            return value
    return os.environ.get("DEEPSCIENTIST_JUDGE_API_KEY") or os.environ.get("OPENAI_API_KEY")


def extract_json_object(text: str) -> dict[str, Any]:
    stripped = str(text or "").strip()
    if not stripped:
        raise PaperJudgeError("Paper judge API returned an empty response.")
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start < 0 or end <= start:
            raise PaperJudgeError("Paper judge API response did not contain a JSON object.")
        parsed = json.loads(stripped[start : end + 1])
    if not isinstance(parsed, dict):
        raise PaperJudgeError("Paper judge API JSON response must be an object.")
    return parsed


class OpenAICompatibleJudgeClient:
    def __init__(self, config: JudgeClientConfig) -> None:
        self.config = config

    def complete_json(self, messages: list[dict[str, str]]) -> tuple[dict[str, Any], dict[str, Any]]:
        api_base = str(self.config.api_base or os.environ.get("DEEPSCIENTIST_JUDGE_API_BASE") or os.environ.get("OPENAI_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
        model = str(self.config.model or os.environ.get("DEEPSCIENTIST_JUDGE_MODEL") or "").strip()
        if not model:
            raise PaperJudgeError("Paper judge model is not configured.")
        api_key = resolve_api_key(self.config)
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": float(self.config.temperature),
            "max_tokens": int(self.config.max_output_tokens),
            "response_format": {"type": "json_object"},
        }
        thinking = str(self.config.thinking or "auto").strip().lower()
        if thinking in {"enabled", "disabled"}:
            payload["thinking"] = {"type": thinking}
        elif "api.deepseek.com" in api_base.lower():
            # DeepSeek may spend the entire completion budget on hidden reasoning,
            # leaving JSON-mode content empty. Structured judging needs the JSON answer.
            payload["thinking"] = {"type": "disabled"}
        try:
            with httpx.Client(timeout=float(self.config.timeout_seconds)) as client:
                empty_attempts: list[dict[str, Any]] = []
                max_attempts = max(1, int(self.config.empty_response_max_attempts))
                for attempt in range(1, max_attempts + 1):
                    response = client.post(f"{api_base}/chat/completions", headers=headers, json=payload)
                    response.raise_for_status()
                    raw = response.json()
                    try:
                        content = str(raw["choices"][0]["message"]["content"] or "")
                    except (KeyError, IndexError, TypeError):
                        raise PaperJudgeError(
                            "Paper judge API response did not include choices[0].message.content.",
                            details={"raw": raw},
                        )
                    if content.strip():
                        if empty_attempts:
                            raw["_judge_retry"] = {
                                "attempt_count": attempt,
                                "empty_attempts": empty_attempts,
                            }
                        return extract_json_object(content), raw
                    choice = raw.get("choices", [{}])[0] if isinstance(raw.get("choices"), list) and raw.get("choices") else {}
                    empty_attempts.append(
                        {
                            "attempt": attempt,
                            "finish_reason": choice.get("finish_reason") if isinstance(choice, dict) else None,
                            "usage": raw.get("usage"),
                        }
                    )
                    completion_details = (
                        raw.get("usage", {}).get("completion_tokens_details", {})
                        if isinstance(raw.get("usage"), dict)
                        else {}
                    )
                    if (
                        "api.deepseek.com" in api_base.lower()
                        and isinstance(completion_details, dict)
                        and int(completion_details.get("reasoning_tokens") or 0) > 0
                    ):
                        payload["thinking"] = {"type": "disabled"}
                    payload["messages"] = [
                        *messages,
                        {
                            "role": "user",
                            "content": (
                                "The previous response was empty. Return exactly one non-empty JSON object matching "
                                "the requested output contract. Do not return whitespace, Markdown, or commentary."
                            ),
                        },
                    ]
                raise PaperJudgeError(
                    "Paper judge API returned empty content after automatic retries.",
                    details={"attempts": empty_attempts, "model": model},
                )
        except httpx.HTTPStatusError as exc:
            response_text = str(exc.response.text or "").strip()
            raise PaperJudgeError(
                "Paper judge API request failed.",
                details={
                    "error": str(exc),
                    "status_code": exc.response.status_code,
                    "url": str(exc.request.url),
                    "response": response_text[:4000] or None,
                    "model": model,
                },
            ) from exc
        except httpx.HTTPError as exc:
            raise PaperJudgeError(
                "Paper judge API request failed.",
                details={"error": str(exc), "url": f"{api_base}/chat/completions", "model": model},
            ) from exc
        raise PaperJudgeError("Paper judge API request failed without a response.")
