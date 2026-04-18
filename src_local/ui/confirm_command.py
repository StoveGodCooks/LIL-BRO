"""Confirm-before-execute modal for shell commands.

Like Claude Code — the model proposes a command, the user sees it
and presses Enter to approve or Escape to deny.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Static


class ConfirmCommandScreen(ModalScreen[bool]):
    """Modal that shows a shell command and waits for user approval."""

    DEFAULT_CSS = """
    ConfirmCommandScreen {
        align: center middle;
    }
    #confirm-container {
        width: 80;
        max-height: 18;
        border: round #3A3A3A;
        padding: 1 2;
        background: #1A1A1A;
    }
    #confirm-title {
        width: 100%;
        content-align: center middle;
        color: #E8A838;
        text-style: bold;
        margin-bottom: 1;
    }
    #confirm-command {
        width: 100%;
        padding: 1 2;
        background: #0e0e0e;
        color: #E8E8E8;
        margin-bottom: 1;
    }
    #confirm-footer {
        width: 100%;
        content-align: center middle;
        color: #888888;
        dock: bottom;
    }
    """

    BINDINGS = [
        Binding("enter", "approve", "Run", priority=True),
        Binding("escape", "deny", "Deny", priority=True),
    ]

    def __init__(self, command: str) -> None:
        super().__init__()
        self._command = command

    def compose(self) -> ComposeResult:
        with Container(id="confirm-container"):
            yield Static("RUN COMMAND?", id="confirm-title")
            yield Static(f"$ {self._command}", id="confirm-command")
            yield Static("[Enter approve / Esc deny]", id="confirm-footer")

    def action_approve(self) -> None:
        self.dismiss(True)

    def action_deny(self) -> None:
        self.dismiss(False)
