from __future__ import annotations

import json
import sys
from typing import Any

from ..shared import generate_id
from .simple_cli import SimpleCliRunner


class QwenRunner(SimpleCliRunner):
    """Runner for Qwen (通义千问) via the Alibaba Cloud Bailian API.

    Unlike the CLI-backed runners, Qwen has no local agent binary. This runner
    launches ``deepscientist.runners.qwen_agent`` as a Python subprocess that
    drives the DashScope OpenAI-compatible endpoint directly and streams JSONL
    events back on stdout.
    """

    runner_name = "qwen"

    def _command_uses_stdin_prompt(self) -> bool:
        return True

    def _build_command(
        self,
        request: Any,
        prompt: str,
        *,
        runner_config: dict[str, Any] | None = None,
    ) -> list[str]:
        resolved_runner_config = runner_config if isinstance(runner_config, dict) else self._load_runner_config()
        command = [sys.executable, "-m", "deepscientist.runners.qwen_agent"]

        normalized_model = str(request.model or resolved_runner_config.get("model") or "").strip()
        if normalized_model.lower() not in {"", "inherit", "default", "qwen-default"}:
            command.extend(["--model", normalized_model])

        base_url = str(resolved_runner_config.get("base_url") or "").strip()
        if base_url:
            command.extend(["--base-url", base_url])

        temperature = resolved_runner_config.get("temperature")
        if temperature is not None:
            try:
                command.extend(["--temperature", str(float(temperature))])
            except (TypeError, ValueError):
                pass

        return command

    def _translate_event(
        self,
        payload: dict[str, Any],
        *,
        raw_line: str,
        quest_id: str,
        run_id: str,
        skill_id: str,
        created_at: str,
        translation_state: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], list[str]]:
        event_type = str(payload.get("event") or "").strip()
        events: list[dict[str, Any]] = []
        texts: list[str] = []

        if event_type == "agent_message":
            text = str(payload.get("text") or "").strip()
            if text:
                texts.append(text)
                events.append(
                    {
                        "event_id": generate_id("evt"),
                        "type": "runner.agent_message",
                        "quest_id": quest_id,
                        "run_id": run_id,
                        "source": self.runner_name,
                        "skill_id": skill_id,
                        "text": text,
                        "stream_id": run_id,
                        "message_id": run_id,
                        "created_at": created_at,
                    }
                )
            return events, texts

        if event_type == "reasoning":
            text = str(payload.get("text") or "").strip()
            if text:
                events.append(
                    {
                        "event_id": generate_id("evt"),
                        "type": "runner.reasoning",
                        "quest_id": quest_id,
                        "run_id": run_id,
                        "source": self.runner_name,
                        "skill_id": skill_id,
                        "text": text,
                        "stream_id": run_id,
                        "message_id": run_id,
                        "kind": "thinking",
                        "created_at": created_at,
                    }
                )
            return events, texts

        if event_type == "tool_call":
            events.append(
                {
                    "event_id": generate_id("evt"),
                    "type": "runner.tool_call",
                    "quest_id": quest_id,
                    "run_id": run_id,
                    "source": self.runner_name,
                    "skill_id": skill_id,
                    "tool_call_id": str(payload.get("tool_call_id") or generate_id("tool")),
                    "tool_name": str(payload.get("tool_name") or "tool"),
                    "status": "calling",
                    "args": str(payload.get("args") or ""),
                    "created_at": created_at,
                }
            )
            return events, texts

        if event_type == "tool_result":
            events.append(
                {
                    "event_id": generate_id("evt"),
                    "type": "runner.tool_result",
                    "quest_id": quest_id,
                    "run_id": run_id,
                    "source": self.runner_name,
                    "skill_id": skill_id,
                    "tool_call_id": str(payload.get("tool_call_id") or generate_id("tool")),
                    "tool_name": str(payload.get("tool_name") or "tool"),
                    "status": str(payload.get("status") or "completed"),
                    "output": str(payload.get("output") or ""),
                    "created_at": created_at,
                }
            )
            return events, texts

        if event_type == "fatal_error":
            text = str(payload.get("text") or "").strip()
            translation_state["fatal_error"] = text
            translation_state["abort_process"] = True
            if text:
                events.append(
                    {
                        "event_id": generate_id("evt"),
                        "type": "runner.error",
                        "quest_id": quest_id,
                        "run_id": run_id,
                        "source": self.runner_name,
                        "skill_id": skill_id,
                        "text": text,
                        "created_at": created_at,
                    }
                )
            return events, texts

        return events, texts
