"""Multi-line compose modal.

Pops open on F3 -- gives you a full TextArea for pasting stack traces,
writing multi-paragraph prompts, etc.

Contract:
  Ctrl+S submits (returns text).
  Esc cancels (returns None).
"""

from __future__ import annotations

from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Static, TextArea


class ComposeScreen(ModalScreen[str | None]):
    """Floating multi-line compose box."""

    DEFAULT_CSS = """
    ComposeScreen {
        align: center middle;
    }
    #compose-container {
        width: 90;
        height: 70%;
        border: round #3A3A3A;
        padding: 1 2;
        background: #1A1A1A;
    }
    #compose-title {
        width: 100%;
        content-align: center middle;
        color: #A8D840;
        text-style: bold;
    }
    #compose-subtitle {
        width: 100%;
        content-align: center middle;
        color: #888888;
        margin-bottom: 1;
    }
    #compose-textarea {
        height: 1fr;
    }
    #compose-footer {
        width: 100%;
        content-align: center middle;
        color: #888888;
        dock: bottom;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", priority=True),
        Binding("ctrl+s", "submit", "Send", priority=True),
    ]

    def __init__(self, initial_text: str = "", target_label: str = "") -> None:
        super().__init__()
        self._initial_text = initial_text
        self._target_label = target_label or "agent"

    def compose(self) -> ComposeResult:
        with Container(id="compose-container"):
            yield Static(
                f"COMPOSE -> {self._target_label}",
                id="compose-title",
            )
            yield Static(
                "multi-line input -- newlines allowed -- paste freely",
                id="compose-subtitle",
            )
            yield TextArea(
                self._initial_text,
                id="compose-textarea",
                soft_wrap=True,
            )
            yield Static(
                "[Ctrl+S send / Esc cancel]",
                id="compose-footer",
            )

    def on_mount(self) -> None:
        textarea = self.query_one("#compose-textarea", TextArea)
        textarea.focus()
        try:
            textarea.cursor_location = textarea.document.end
        except Exception:  # noqa: BLE001
            pass

    def action_submit(self) -> None:
        textarea = self.query_one("#compose-textarea", TextArea)
        text = textarea.text.strip()
        if not text:
            self.dismiss(None)
            return
        self.dismiss(text)

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_key(self, event: events.Key) -> None:
        """Belt-and-suspenders: catch Ctrl+S if TextArea swallows it."""
        if event.key == "ctrl+s":
            event.stop()
            event.prevent_default()
            self.action_submit()
