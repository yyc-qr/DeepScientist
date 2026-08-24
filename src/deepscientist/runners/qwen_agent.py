from __future__ import annotations

"""Qwen runner agent.

This module is the executable half of the Qwen runner. It is launched by
``QwenRunner`` as a subprocess (``python -m deepscientist.runners.qwen_agent``)
and is *not* an external CLI. It:

1. reads the built prompt from stdin,
2. connects to the three public MCP namespaces (``memory``, ``artifact``,
   ``bash_exec``) as an MCP client,
3. runs a tool-calling loop against the Alibaba Cloud Bailian (DashScope)
   OpenAI-compatible chat completions endpoint, and
4. emits JSONL events on stdout for ``QwenRunner._translate_event`` to turn
   into quest events.

Environment contract (set by ``SimpleCliRunner``):
``DEEPSCIENTIST_HOME``, ``DS_QUEST_ROOT``, ``DS_QUEST_ID``, etc., plus
``QWEN_API_KEY`` (from ``runners.qwen.env`` or the ambient environment).
"""

import argparse
import asyncio
import json
import os
import sys
from contextlib import AsyncExitStack
from typing import Any
from urllib import request as urllib_request

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from ..shared import generate_id

DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEFAULT_MODEL = "qwen-plus"
BUILTIN_MCP_SERVERS = ("memory", "artifact", "bash_exec")
MAX_TOOL_ITERATIONS = 25

_SYSTEM_PROMPT = (
    "You are the DeepScientist Qwen research agent. You work inside a quest "
    "repository and pursue the research goal you are given. Use the provided "
    "tools (bash_exec, artifact, memory) to inspect files, run commands, and "
    "record findings. Prefer concrete actions over speculation, and always "
    "leave the quest in a clean, committed state."
)


def _emit(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _read_prompt() -> str:
    try:
        return sys.stdin.read()
    except Exception:  # pragma: no cover - stdin is always attached
        return ""


def _http_post_json(url: str, payload: dict[str, Any], api_key: str, *, timeout: float = 120.0) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib_request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )
    with urllib_request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _tool_schema(api_name: str, description: str, input_schema: Any) -> dict[str, Any]:
    parameters = input_schema if isinstance(input_schema, dict) else {"type": "object", "properties": {}}
    return {
        "type": "function",
        "function": {
            "name": api_name,
            "description": description or "",
            "parameters": parameters,
        },
    }


def _render_tool_result(result: Any) -> str:
    parts: list[str] = []
    content = getattr(result, "content", None)
    if content:
        for item in content:
            text = getattr(item, "text", None)
            if isinstance(text, str):
                parts.append(text)
            else:
                try:
                    parts.append(json.dumps(item, ensure_ascii=False, default=str))
                except Exception:
                    parts.append(str(item))
    if not parts:
        structured = getattr(result, "structuredContent", None)
        if structured is not None:
            parts.append(json.dumps(structured, ensure_ascii=False, default=str))
    return "\n".join(part for part in parts if part).strip()


async def _run_agent(
    *,
    api_key: str,
    model: str,
    base_url: str,
    prompt: str,
    temperature: float,
) -> int:
    sessions: dict[str, ClientSession] = {}
    tools_for_api: list[dict[str, Any]] = []
    tool_index: dict[str, tuple[str, str]] = {}

    async with AsyncExitStack() as stack:
        for server_name in BUILTIN_MCP_SERVERS:
            params = StdioServerParameters(
                command=sys.executable,
                args=["-m", "deepscientist.mcp.server", "--namespace", server_name],
                env=dict(os.environ),
            )
            read_stream, write_stream = await stack.enter_async_context(stdio_client(params))
            session = await stack.enter_async_context(ClientSession(read_stream, write_stream))
            await session.initialize()
            sessions[server_name] = session

        for server_name, session in sessions.items():
            tools_result = await session.list_tools()
            for tool in tools_result.tools:
                api_name = f"{server_name}__{tool.name}"
                tool_index[api_name] = (server_name, tool.name)
                tools_for_api.append(_tool_schema(api_name, tool.description, tool.inputSchema))

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]

        for _ in range(MAX_TOOL_ITERATIONS):
            request_payload: dict[str, Any] = {
                "model": model,
                "messages": messages,
                "temperature": temperature,
            }
            if tools_for_api:
                request_payload["tools"] = tools_for_api

            try:
                response = await asyncio.to_thread(
                    _http_post_json, f"{base_url.rstrip('/')}/chat/completions", request_payload, api_key
                )
            except Exception as exc:
                _emit({"event": "fatal_error", "text": f"Qwen API call failed: {exc}"})
                return 1

            choice = (response.get("choices") or [{}])[0]
            message = choice.get("message") if isinstance(choice.get("message"), dict) else {}
            content = str(message.get("content") or "").strip()
            reasoning = str(message.get("reasoning_content") or "").strip()
            tool_calls = message.get("tool_calls") or []

            if reasoning:
                _emit({"event": "reasoning", "text": reasoning})
            if content:
                _emit({"event": "agent_message", "text": content})

            if not tool_calls:
                break

            assistant_turn: dict[str, Any] = {
                "role": "assistant",
                "content": content or None,
                "tool_calls": tool_calls,
            }
            messages.append(assistant_turn)

            for tool_call in tool_calls:
                function = tool_call.get("function") if isinstance(tool_call.get("function"), dict) else {}
                api_name = str(function.get("name") or "")
                tool_call_id = str(tool_call.get("id") or generate_id("tool"))
                raw_args = function.get("arguments")
                if isinstance(raw_args, str):
                    try:
                        args = json.loads(raw_args) if raw_args.strip() else {}
                    except json.JSONDecodeError:
                        args = {"_raw": raw_args}
                else:
                    args = raw_args if isinstance(raw_args, dict) else {}

                _emit(
                    {
                        "event": "tool_call",
                        "tool_call_id": tool_call_id,
                        "tool_name": api_name,
                        "args": json.dumps(args, ensure_ascii=False),
                    }
                )

                server_name, tool_name = tool_index.get(api_name, ("", api_name))
                session = sessions.get(server_name)
                if session is None:
                    output = f"Unknown tool `{api_name}`."
                    _emit(
                        {
                            "event": "tool_result",
                            "tool_call_id": tool_call_id,
                            "tool_name": api_name,
                            "output": output,
                            "status": "failed",
                        }
                    )
                    messages.append({"role": "tool", "tool_call_id": tool_call_id, "content": output})
                    continue

                try:
                    result = await session.call_tool(tool_name, args)
                    output = _render_tool_result(result)
                    status = "failed" if getattr(result, "isError", False) else "completed"
                except Exception as exc:
                    output = str(exc)
                    status = "failed"

                _emit(
                    {
                        "event": "tool_result",
                        "tool_call_id": tool_call_id,
                        "tool_name": api_name,
                        "output": output,
                        "status": status,
                    }
                )
                messages.append({"role": "tool", "tool_call_id": tool_call_id, "content": output})

    return 0


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="qwen_agent", description="DeepScientist Qwen runner agent")
    parser.add_argument("--model", default=None, help="Qwen model name (default: qwen-plus)")
    parser.add_argument("--base-url", default=None, help="OpenAI-compatible API base URL")
    parser.add_argument("--temperature", type=float, default=0.2, help="Sampling temperature")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(list(argv) if argv is not None else sys.argv[1:])
    api_key = str(os.environ.get("QWEN_API_KEY", "")).strip()
    if not api_key:
        _emit(
            {
                "event": "fatal_error",
                "text": "QWEN_API_KEY is not set. Add it to `runners.qwen.env` in runners.yaml or the environment.",
            }
        )
        return 1

    model = str(args.model or os.environ.get("QWEN_MODEL") or DEFAULT_MODEL).strip() or DEFAULT_MODEL
    if model in {"inherit", "default"}:
        model = DEFAULT_MODEL
    base_url = str(args.base_url or os.environ.get("QWEN_BASE_URL") or DEFAULT_BASE_URL).strip() or DEFAULT_BASE_URL
    prompt = _read_prompt().strip()

    try:
        return asyncio.run(
            _run_agent(
                api_key=api_key,
                model=model,
                base_url=base_url,
                prompt=prompt,
                temperature=args.temperature,
            )
        )
    except KeyboardInterrupt:  # pragma: no cover
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
