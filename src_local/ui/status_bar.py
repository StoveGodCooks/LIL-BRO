"""Status bar for LIL BRO LOCAL.

Shows the current model, busy indicator, and active agent.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.timer import Timer
from textual.widgets import Static

if TYPE_CHECKING:
    from src_local.agents.ollama_agent import OllamaAgent


class StatusBar(Horizontal):
    """One-line status strip above the input bar."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._bro_a: "OllamaAgent | None" = None
        self._bro_b: "OllamaAgent | None" = None
        self._busy_timer: Timer | None = None
        self._last_busy_text: str = ""
        self._model_name: str = ""

    def compose(self) -> ComposeResult:
        yield Static("", id="status-model")
        yield Static("", id="status-busy")
        yield Static("", id="status-info")

    def on_mount(self) -> None:
        self._busy_timer = self.set_interval(0.5, self._tick_busy)
        if self._model_name:
            self.query_one("#status-model", Static).update(
                f"model: {self._model_name}"
            )

    def set_model(self, name: str) -> None:
        self._model_name = name
        try:
            self.query_one("#status-model", Static).update(f"model: {name}")
        except Exception:
            pass

    def set_info(self, text: str) -> None:
        try:
            self.query_one("#status-info", Static).update(text)
        except Exception:
            pass

    def attach_agents(
        self,
        bro_a: "OllamaAgent",
        bro_b: "OllamaAgent",
    ) -> None:
        self._bro_a = bro_a
        self._bro_b = bro_b

    def _tick_busy(self) -> None:
        parts = []
        for label, agent in [("A", self._bro_a), ("B", self._bro_b)]:
            if agent is None:
                continue
            elapsed = agent.busy_for()
            if elapsed is not None:
                parts.append(f"Bro {label} thinking {int(elapsed)}s")

        text = " · ".join(parts) if parts else ""
        if text != self._last_busy_text:
            self._last_busy_text = text
            try:
                self.query_one("#status-busy", Static).update(text)
            except Exception:
                pass
