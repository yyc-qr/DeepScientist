from __future__ import annotations

from .claude import ClaudeRunner
from .codex import CodexRunner
from .kimi import KimiRunner
from .opencode import OpenCodeRunner
from .qwen import QwenRunner
from .registry import register_runner


def register_builtin_runners(
    *,
    codex_runner: CodexRunner,
    claude_runner: ClaudeRunner,
    kimi_runner: KimiRunner,
    opencode_runner: OpenCodeRunner,
    qwen_runner: QwenRunner,
) -> None:
    register_runner("codex", lambda **_: codex_runner)
    register_runner("claude", lambda **_: claude_runner)
    register_runner("kimi", lambda **_: kimi_runner)
    register_runner("opencode", lambda **_: opencode_runner)
    register_runner("qwen", lambda **_: qwen_runner)
