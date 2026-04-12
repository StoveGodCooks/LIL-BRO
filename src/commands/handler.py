"""Slash command handler for LIL BRO LOCAL.

Handles /help, /model, /clear, /quit, and other local-specific commands.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from src.agents.ollama_agent import OllamaAgent
    from src.config import Config


Target = Literal["a", "b"]


@dataclass
class CommandResult:
    bypass_agent: bool = False
    message: str = ""
    rewritten_prompt: str | None = None
    forced_target: Target | None = None
    clear_panel: bool = False
    quit: bool = False


class CommandHandler:
    """Parses and dispatches slash commands."""

    def __init__(
        self,
        config: "Config",
        bro_a: "OllamaAgent | None" = None,
        bro_b: "OllamaAgent | None" = None,
    ) -> None:
        self._config = config
        self._bro_a = bro_a
        self._bro_b = bro_b

    def handle(self, text: str) -> CommandResult:
        parts = text.strip().split(None, 1)
        cmd = parts[0].lower()
        arg = parts[1].strip() if len(parts) > 1 else ""

        if cmd == "/quit" or cmd == "/q":
            return CommandResult(bypass_agent=True, quit=True)

        if cmd == "/help" or cmd == "/h":
            return self._cmd_help()

        if cmd == "/clear":
            return CommandResult(bypass_agent=True, clear_panel=True)

        if cmd == "/model":
            return self._cmd_model(arg)

        if cmd == "/models":
            return self._cmd_models()

        if cmd == "/history":
            return self._cmd_history(arg)

        if cmd == "/explain":
            return self._cmd_explain(arg)

        if cmd == "/status":
            return self._cmd_status()

        return CommandResult(
            bypass_agent=True,
            message=f"Unknown command: {cmd}\nType /help for available commands.",
        )

    def _cmd_help(self) -> CommandResult:
        msg = (
            "LIL BRO LOCAL — Commands\n"
            "─────────────────────────\n"
            "/help         — Show this help\n"
            "/model <name> — Switch Ollama model\n"
            "/models       — List available models\n"
            "/clear        — Clear the active panel\n"
            "/history clear — Clear conversation history\n"
            "/explain <topic> — Ask Bro B to explain a topic\n"
            "/status       — Show current config + agent state\n"
            "/quit         — Exit LIL BRO LOCAL\n"
            "\n"
            "Keyboard shortcuts:\n"
            "  Tab        — Switch active pane\n"
            "  Ctrl+C     — Port Bro A reply → Bro B input\n"
            "  Ctrl+B     — Port Bro B reply → Bro A input\n"
            "  Ctrl+R     — Retry last prompt\n"
            "  Escape     — Cancel current turn\n"
            "  Ctrl+Q     — Quit"
        )
        return CommandResult(bypass_agent=True, message=msg)

    def _cmd_model(self, arg: str) -> CommandResult:
        if not arg:
            current = self._config.ollama.model
            return CommandResult(
                bypass_agent=True,
                message=f"Current model: {current}\nUsage: /model <ollama-tag>",
            )
        # Switch model on both agents.
        for agent in (self._bro_a, self._bro_b):
            if agent is not None:
                agent.model = arg
        return CommandResult(
            bypass_agent=True,
            message=f"Switched both agents to model: {arg}",
        )

    def _cmd_models(self) -> CommandResult:
        return CommandResult(
            bypass_agent=True,
            message=(
                "To see available models, run in a terminal:\n"
                "  ollama list\n\n"
                "To pull a new model:\n"
                "  ollama pull qwen2.5-coder:7b"
            ),
        )

    def _cmd_history(self, arg: str) -> CommandResult:
        if arg.lower() == "clear":
            for agent in (self._bro_a, self._bro_b):
                if agent is not None:
                    agent.clear_history()
            return CommandResult(
                bypass_agent=True,
                message="Conversation history cleared for both agents.",
            )
        return CommandResult(
            bypass_agent=True,
            message="Usage: /history clear",
        )

    def _cmd_explain(self, arg: str) -> CommandResult:
        if not arg:
            return CommandResult(
                bypass_agent=True,
                message="Usage: /explain <topic>\nRoutes to Bro B (helper).",
            )
        prompt = (
            f"Explain this topic clearly and concisely: {arg}\n\n"
            "Structure your answer as:\n"
            "1. What it is (1-2 sentences)\n"
            "2. Why it matters\n"
            "3. A simple example\n"
            "4. Common pitfalls"
        )
        return CommandResult(
            bypass_agent=False,
            rewritten_prompt=prompt,
            forced_target="b",
        )

    def _cmd_status(self) -> CommandResult:
        lines = [
            "LIL BRO LOCAL — Status",
            "──────────────────────",
            f"Ollama URL: {self._config.ollama.base_url}",
            f"Model: {self._config.ollama.model}",
            f"Context window: {self._config.ollama.context_window}",
            f"Temperature: {self._config.ollama.temperature}",
        ]
        for label, agent in [("Bro A", self._bro_a), ("Bro B", self._bro_b)]:
            if agent is not None:
                busy = "thinking" if agent.is_busy() else "idle"
                history = len(agent._history)
                lines.append(f"{label}: {busy}, {history} messages in history")
        return CommandResult(bypass_agent=True, message="\n".join(lines))
