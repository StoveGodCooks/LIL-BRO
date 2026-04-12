"""Startup screen for LIL BRO LOCAL.

Checks Ollama availability, shows available models, and guides the
user through setup if needed.
"""

from __future__ import annotations

import asyncio

from textual.app import ComposeResult
from textual.containers import Center, Vertical
from textual.screen import Screen
from textual.widgets import Button, Label, Static


LOGO = r"""
  _     ___ _       ____  ____   ___
 | |   |_ _| |     | __ )|  _ \ / _ \
 | |    | || |     |  _ \| |_) | | | |
 | |___ | || |___  | |_) |  _ <| |_| |
 |_____|___|_____| |____/|_| \_\\___/
           L O C A L   M O D E
"""


class StartupScreen(Screen):
    """Welcome + Ollama readiness check."""

    def __init__(self, ollama_url: str = "http://127.0.0.1:11434", **kwargs):
        super().__init__(**kwargs)
        self._ollama_url = ollama_url

    def compose(self) -> ComposeResult:
        with Center():
            with Vertical(id="startup-box"):
                yield Static(LOGO, id="logo")
                yield Label("Checking Ollama...", id="status-label")
                yield Static("", id="models-label")
                yield Static("", id="instructions")
                yield Button("Continue", id="continue-btn", variant="success")

    async def on_mount(self) -> None:
        btn = self.query_one("#continue-btn", Button)
        btn.disabled = True

        status_label = self.query_one("#status-label", Label)
        models_label = self.query_one("#models-label", Static)
        instructions = self.query_one("#instructions", Static)

        from src_local.agents.ollama_agent import check_ollama_health

        health = await check_ollama_health(self._ollama_url)

        if not health["running"]:
            status_label.update("Ollama is NOT running")
            instructions.update(
                "To get started:\n\n"
                "  1. Install Ollama from https://ollama.com/download\n"
                "  2. Run: ollama serve\n"
                "  3. Pull a model: ollama pull qwen2.5-coder:7b\n"
                "  4. Restart LIL BRO LOCAL\n\n"
                "Press Continue to enter anyway (limited mode)."
            )
            btn.disabled = False
            btn.label = "Continue (offline)"
            return

        version = health["version"] or "unknown"
        models = health["models"]

        status_label.update(f"Ollama v{version} — connected")

        if models:
            model_list = "\n".join(f"  · {m}" for m in models[:10])
            models_label.update(f"Available models:\n{model_list}")
        else:
            models_label.update(
                "No models found! Pull one first:\n"
                "  ollama pull qwen2.5-coder:7b"
            )

        btn.disabled = False

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "continue-btn":
            self.app.pop_screen()
